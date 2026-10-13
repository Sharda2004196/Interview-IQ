"""fetch_url tool — link -> text, the Mode E source.

YouTube links -> captions via youtube-transcript-api (free, no key).
Articles/docs pages -> clean text via trafilatura (free, strips nav/ads).
Output shape mirrors parse_file ({title/file, chars, text}) so everything
downstream (upsert, retrieve, generator) works unchanged.

Graceful failures (never hallucinated questions):
- video with no captions -> ValueError naming it (transcribe pipeline is backlog)
- unreachable / JS-walled / login pages -> ValueError naming the URL
"""

import re
import sys
from pathlib import Path

from google.adk.tools import FunctionTool

from .. import config  # noqa: F401 — side effect: loads interviewiq_agent/.env

_MAX_CHARS = 60_000  # safety cap; Pinecone chunking happens at upsert
_PIECE = 2000  # translation chunk size (small bills, dodges transport landmine)
_TRANSLATE_WORKERS = 4
_CACHE_DIR = Path(__file__).resolve().parents[2] / "backend" / "uploads" / ".translate_cache"

_YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?.*v=|shorts/|embed/|live/)|youtu\.be/)([\w-]{11})"
)


def _video_id(url: str) -> str | None:
    m = _YOUTUBE_RE.search(url)
    return m.group(1) if m else None


_WORKER = str(Path(__file__).with_name("translate_worker.py"))


def _pieces(text: str) -> list:
    parts, start = [], 0
    while start < len(text):
        end = min(start + _PIECE, len(text))
        if end < len(text):
            cut = text.rfind(" ", start + _PIECE - 200, end)
            end = cut if cut > start else end
        parts.append(text[start:end])
        start = end
    return parts


def _translate_piece(piece: str) -> str:
    """One pristine worker call. Raises ValueError with stderr tail on failure."""
    import subprocess

    proc = subprocess.run(
        [sys.executable, _WORKER],
        input=piece.encode("utf-8"),
        capture_output=True,
        timeout=180,
    )
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 or not out:
        err = proc.stderr.decode("utf-8", errors="replace")[-200:]
        raise ValueError(f"Translation piece failed: {err}")
    return out


def _to_english(text: str, lang: str, cache_key: str = "") -> tuple[str, bool]:
    """Translate non-English transcripts once at ingest (Lite).

    Shape (all lessons baked in):
    - pristine file-based worker (never `python -c` + stdin for genai transport).
    - bytes in/out UTF-8 (Windows cp1252 must never touch the stream).
    - ~2000-char pieces in parallel (4 workers): big single requests die deep
      in transport, and serial pieces were the 84-second silence in Mode E logs.
    - disk cache per video id: transcripts are static, second run is instant.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    if lang.startswith("en"):
        return text, False
    t0 = time.time()
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_key = re.sub(r"[^\w-]", "_", cache_key or "notranslate")[:64]
    cache_file = _CACHE_DIR / f"{safe_key}.{lang}.en.txt"
    if cache_file.is_file():
        print(f"[fetch_url] translation cache HIT ({cache_file.name})", flush=True)
        return cache_file.read_text(encoding="utf-8"), True
    parts = _pieces(text[:_MAX_CHARS])
    print(f"[fetch_url] translating {len(parts)} pieces ×4 workers...", flush=True)
    with ThreadPoolExecutor(max_workers=_TRANSLATE_WORKERS) as pool:
        done = list(pool.map(_translate_piece, parts))
    out = "\n".join(done)
    cache_file.write_text(out, encoding="utf-8")
    print(f"[fetch_url] translated {len(text)} chars in {time.time() - t0:.0f}s", flush=True)
    return out, True
    return out, True


def _fetch_youtube(url: str, video_id: str) -> dict:
    from youtube_transcript_api import (
        NoTranscriptFound,
        TranscriptsDisabled,
        YouTubeTranscriptApi,
    )

    transcript = None
    lang = ""
    for langs in (["en"], ["hi"]):
        try:
            transcript = YouTubeTranscriptApi().fetch(video_id, languages=langs)
            lang = getattr(transcript, "language_code", langs[0])
            break
        except (NoTranscriptFound, TranscriptsDisabled):
            continue
    if transcript is None:
        raise ValueError(
            f"No English or Hindi captions on this video ({url}) — interview needs text. "
            "Try a captioned lecture/tutorial instead."
        )
    text = " ".join(s.text for s in transcript.snippets).strip()
    if not text:
        raise ValueError(f"Transcript came back empty for {url}.")
    text, translated = _to_english(text, lang, cache_key=f"yt-{video_id}")
    title = f"youtube:{video_id}" + (f" (translated from {lang})" if translated else "")
    return {"title": title, "text": text, "source": "youtube"}


def _fetch_article(url: str) -> dict:
    import trafilatura

    html = trafilatura.fetch_url(url)
    if not html:
        raise ValueError(
            f"Could not download {url} — page may need login, block bots, "
            "or render via JavaScript. Try a public article/docs page instead."
        )
    meta = trafilatura.extract_metadata(html)
    title = getattr(meta, "title", None) or url
    text = (trafilatura.extract(html) or "").strip()
    if len(text) < 200:
        raise ValueError(
            f"Almost no readable text at {url} (got {len(text)} chars) — "
            "page is likely JS-rendered or paywalled."
        )
    return {"title": title, "text": text, "source": "article"}


def fetch_url(url: str) -> dict:
    """Fetch a link's text. Returns {"url","title","chars","text","source"}."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Not a URL: {url!r} (Mode E needs a full link).")
    video_id = _video_id(url)
    got = _fetch_youtube(url, video_id) if video_id else _fetch_article(url)
    text = got["text"]
    return {
        "url": url,
        "title": got["title"],
        "chars": len(text),
        "text": text[:_MAX_CHARS],
        "source": got["source"],
    }


fetch_url_tool = FunctionTool(fetch_url)
