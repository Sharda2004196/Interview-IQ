"""retrieve_context tool — production RAG for resume/upload grounding.

Pipeline per query: clean -> LLM rewrite (Lite, cached) -> embed (Gemini,
cached) + hashed-TF sparse -> single hybrid Pinecone query (top 20) ->
Pinecone rerank to top_k. Metadata (doc_name/chunk_idx) supports filtering.
Upserts parallelize embed + write batches via threads.

All $0: Gemini embeddings + Lite rewrite on the AI Studio key, Pinecone
inference rerank on the Pinecone key. Clients init lazily so `adk web`
loads without keys; calls raise a clear RuntimeError naming the .env key.
"""

import hashlib
import os
import re
from concurrent.futures import ThreadPoolExecutor
from math import sqrt

from google.adk.tools import FunctionTool

from .. import config  # noqa: F401 — side effect: loads interviewiq_agent/.env

EMBED_MODEL = "gemini-embedding-001"  # Gemini, single Google stack w/ generator
EMBED_DIM = 768  # Matryoshka-truncated from 3072 via output_dimensionality
RERANK_MODEL = "pinecone-rerank-v0"  # Pinecone-hosted, same free-tier key
REWRITE_MODEL = "gemini-3.5-flash-lite"  # cheap, 500 RPD headroom
DEFAULT_TOP_K = 5
_RERANK_CANDIDATES = 20
_CHUNK_CHARS = 1500
_CHUNK_OVERLAP = 150
_SPARSE_DIM = 30_000  # hashed-TF buckets, no fitter/package needed
_EMBED_BATCH = 50
_UPSERT_BATCH = 100
_CACHE_MAX = 200

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9•\-\(])")
_TOKEN = re.compile(r"[a-z0-9#+]+")

_embed_cache: dict[str, list[float]] = {}
_rewrite_cache: dict[str, str] = {}
_retrieve_cache: dict[str, dict] = {}
# Semantic cache: scope -> [(query_vector, result)]. Hit only when cosine of the
# rewritten-query embedding clears _SEM_THRESHOLD *within the same scope*, so a
# paraphrase can never pull another namespace/doc/top_k's grounding.
_sem_cache: dict[str, list[tuple[list[float], dict]]] = {}
# Measured on gemini-embedding-001 (2026-09): true paraphrase ~0.85,
# same-doc different question ~0.52-0.73, unrelated ~0.42-0.47.
# 0.80 clears paraphrases with margin while rejecting neighbors.
_SEM_THRESHOLD = 0.80
_SEM_MAX = 200


def _cache_put(cache: dict, key: str, value):
    if len(cache) >= _CACHE_MAX:
        cache.pop(next(iter(cache)))
    cache[key] = value


def _clients():
    from pinecone import Pinecone

    from google import genai

    pinecone_key = os.getenv("PINECONE_API_KEY")
    google_key = os.getenv("GOOGLE_API_KEY")
    if not pinecone_key:
        raise RuntimeError("PINECONE_API_KEY missing in interviewiq_agent/.env")
    if not google_key:
        raise RuntimeError("GOOGLE_API_KEY missing in interviewiq_agent/.env")
    return Pinecone(api_key=pinecone_key), genai.Client(
        api_key=google_key, http_options=config.http_options()
    )


def _index(pc):
    name = os.getenv("PINECONE_INDEX", "interviewiq-kb")
    names = [i["name"] for i in pc.list_indexes()]
    if name not in names:
        pc.create_index(
            name=name,
            dimension=EMBED_DIM,
            metric="dotproduct",  # required for hybrid dense+sparse; rerank fixes ordering
            spec={"serverless": {"cloud": "aws", "region": "us-east-1"}},
        )
    else:
        dim = pc.describe_index(name)["dimension"]
        if dim != EMBED_DIM:
            raise RuntimeError(
                f"Pinecone index '{name}' is {dim}-dim, code expects {EMBED_DIM}. "
                f"Delete it (Pinecone console) so it recreates, or change EMBED_DIM."
            )
    return pc.Index(name)


def _embed_texts(genai_client, texts: list[str]) -> list[list[float]]:
    """Batched Gemini embeddings with cache. One API call per 50 texts."""
    out: list[list[float]] = [None] * len(texts)  # type: ignore[list-item]
    missing, missing_idx = [], []
    for i, t in enumerate(texts):
        hit = _embed_cache.get(t)
        if hit is not None:
            out[i] = hit
        else:
            missing.append(t)
            missing_idx.append(i)
    for start in range(0, len(missing), _EMBED_BATCH):
        batch = missing[start : start + _EMBED_BATCH]
        batch_pos = missing_idx[start : start + _EMBED_BATCH]
        resp = genai_client.models.embed_content(
            model=EMBED_MODEL,
            contents=batch,
            config={"output_dimensionality": EMBED_DIM},
        )
        for t, p, e in zip(batch, batch_pos, resp.embeddings):
            vec = list(e.values)
            _cache_put(_embed_cache, t, vec)
            out[p] = vec
    return out


def _sparse(text: str) -> dict:
    """Hashed TF sparse vector (Pinecone format) — keyword complement to dense."""
    counts: dict[int, float] = {}
    for tok in _TOKEN.findall(text.lower()):
        b = int(hashlib.md5(tok.encode()).hexdigest(), 16) % _SPARSE_DIM
        counts[b] = counts.get(b, 0.0) + 1.0
    norm = sqrt(sum(v * v for v in counts.values())) or 1.0
    idx = sorted(counts)
    return {"indices": idx, "values": [counts[i] / norm for i in idx]}


def _chunk(text: str) -> list[str]:
    """Sentence-aware chunks packed to ~_CHUNK_CHARS, sentence overlap carried."""
    sentences = [s.strip() for s in _SENT_SPLIT.split(text.strip()) if s.strip()]
    if len(sentences) < 2:
        return [text[i : i + _CHUNK_CHARS] for i in range(0, len(text), _CHUNK_CHARS)]
    chunks, current = [], ""
    for sent in sentences:
        if len(current) + len(sent) + 1 > _CHUNK_CHARS and current:
            chunks.append(current)
            overlap = current.split(". ")[-1] if ". " in current else current[-_CHUNK_OVERLAP:]
            current = overlap + " " + sent if overlap != current else sent
        else:
            current = (current + " " + sent).strip()
    if current:
        chunks.append(current)
    return chunks


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sqrt(sum(x * x for x in a)) or 1.0
    nb = sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _sem_lookup(scope: str, vec: list[float]) -> dict | None:
    best, best_score = None, 0.0
    for v, res in _sem_cache.get(scope, []):
        s = _cosine(vec, v)
        if s > best_score:
            best, best_score = res, s
    if best is not None and best_score >= _SEM_THRESHOLD:
        return {**best, "cached": "semantic", "sem_score": round(best_score, 3)}
    return None


def _sem_store(scope: str, vec: list[float], res: dict):
    bucket = _sem_cache.setdefault(scope, [])
    bucket.append((vec, res))
    if len(bucket) > _SEM_MAX:
        del bucket[0]


def _clean_query(query: str) -> str:
    filler = ("please ", "can you ", "could you ", "tell me ", "i want ", "?")
    q = query.strip().lower()
    for f in filler:
        q = q.replace(f, "")
    return " ".join(q.split())[:500] or query[:500]


def _rewrite_query(genai_client, query: str) -> str:
    """Lite rewrite: vague interview question -> focused retrieval query (cached)."""
    hit = _rewrite_cache.get(query)
    if hit is not None:
        return hit
    resp = genai_client.models.generate_content(
        model=REWRITE_MODEL,
        contents=(
            "Rewrite this as a focused search query for retrieving resume/job facts. "
            "Return ONLY the rewritten query, no quotes:\n" + query
        ),
    )
    out = (resp.text or query).strip()[:500] or query
    _cache_put(_rewrite_cache, query, out)
    return out


def upsert_document(text: str, namespace: str, doc_name: str = "upload") -> dict:
    """Chunk + embed + hybrid-upsert one parsed document. Returns {"chunks": n}."""
    if not text or not text.strip():
        raise ValueError("upsert_document got empty text — run parse_file first")
    pc, genai_client = _clients()
    index = _index(pc)
    chunks = _chunk(text)
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = [chunks[i : i + _EMBED_BATCH] for i in range(0, len(chunks), _EMBED_BATCH)]
        embedded = pool.map(lambda b: _embed_texts(genai_client, b), batches)
        vectors = [v for batch_vecs in embedded for v in batch_vecs]
        records = [
            {
                "id": f"{doc_name}-{i}",
                "values": v,
                "sparse_values": _sparse(c),
                "metadata": {"text": c, "doc_name": doc_name, "chunk_idx": i},
            }
            for i, (c, v) in enumerate(zip(chunks, vectors))
        ]
        write_batches = [records[i : i + _UPSERT_BATCH] for i in range(0, len(records), _UPSERT_BATCH)]
        list(pool.map(lambda b: index.upsert(vectors=b, namespace=namespace), write_batches))
    return {"chunks": len(chunks)}


def retrieve_context(
    query: str, namespace: str, top_k: int = DEFAULT_TOP_K, filter_doc: str = ""
) -> dict:
    """Hybrid retrieve (top 20) + rerank to top_k. filter_doc targets one upload."""
    cache_key = f"{namespace}|{filter_doc}|{top_k}|{query}"
    hit = _retrieve_cache.get(cache_key)
    if hit is not None:
        return {**hit, "cached": True}
    pc, genai_client = _clients()
    index = _index(pc)
    cleaned = _clean_query(query)
    # Identity signal = CLEANED embedding (rewrite diverges paraphrases: measured
    # 0.74 rewritten vs 0.85 cleaned). Retrieval still uses the rewritten form.
    clean_vec = _embed_texts(genai_client, [cleaned])[0]
    scope = f"{namespace}|{filter_doc}|{top_k}"
    sem_hit = _sem_lookup(scope, clean_vec)
    if sem_hit is not None:
        _cache_put(_retrieve_cache, cache_key, {k: v for k, v in sem_hit.items() if k != "cached"})
        return sem_hit
    rewritten = _rewrite_query(genai_client, cleaned)
    dense = _embed_texts(genai_client, [rewritten])[0]
    pinecone_filter = {"doc_name": {"$eq": filter_doc}} if filter_doc else None
    res = index.query(
        vector=dense,
        sparse_vector=_sparse(rewritten),
        top_k=_RERANK_CANDIDATES,
        namespace=namespace,
        include_metadata=True,
        filter=pinecone_filter,
    )
    docs = [m["metadata"].get("text", "") for m in res["matches"]]
    if not docs:
        return {"matches": []}
    ranked = pc.inference.rerank(
        model=RERANK_MODEL,
        query=rewritten,
        documents=docs,
        top_n=top_k,
        # Rerank caps query+doc pairs at 512 tokens; our chunks run longer.
        # Truncate at END (chunks are sentence-aligned, head carries the point).
        parameters={"truncate": "END"},
    )
    out = {
        "matches": [
            {"score": round(d["score"], 3), "text": docs[d["index"]]}
            for d in ranked.data
        ]
    }
    _cache_put(_retrieve_cache, cache_key, out)
    _sem_store(scope, clean_vec, out)
    return out


upsert_document_tool = FunctionTool(upsert_document)
retrieve_context_tool = FunctionTool(retrieve_context)
