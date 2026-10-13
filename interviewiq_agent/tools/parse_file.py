"""parse_file tool — deterministic text extraction from uploads.

Judgment (topic/field detection, question writing) stays with the LLM in
question_generator; this module only extracts bytes -> text + metadata.
Supports: .pdf (pypdf), .docx (python-docx), .txt/.md (utf-8).
"""

from pathlib import Path

from google.adk.tools import FunctionTool

_MAX_CHARS = 60_000  # safety cap per file; Pinecone chunking happens at upsert


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(path: Path) -> str:
    import docx

    doc = docx.Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


_READERS = {".pdf": _read_pdf, ".docx": _read_docx, ".txt": _read_txt, ".md": _read_txt}


def parse_file(file_path: str) -> dict:
    """Extract text from an uploaded file.

    Returns {"file": name, "chars": n, "truncated": bool, "text": ...}.
    Raises ValueError on unsupported type or empty result.
    """
    path = Path(file_path)
    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        raise ValueError(f"Unsupported file type: {path.suffix} (use pdf/docx/txt/md)")
    if not path.is_file():
        raise ValueError(
            f"File not found: {file_path} — use an absolute path "
            "(adk web resolves bare filenames against its own working dir, not yours). "
            "Supported types: pdf, docx, txt, md."
        )
    text = reader(path).strip()
    if not text:
        raise ValueError(f"No extractable text in: {file_path}")
    truncated = len(text) > _MAX_CHARS
    return {
        "file": path.name,
        "chars": len(text),
        "truncated": truncated,
        "text": text[:_MAX_CHARS],
    }


parse_file_tool = FunctionTool(parse_file)
