"""Translation worker — runs as `python translate_worker.py < stdin`, prints English.

Single text in, single translation out. The PARENT parallelizes pieces and
caches per video; this worker stays dumb on purpose.

Deliberately dependency-light (stdlib + genai ONLY, never ADK): it executes in
a pristine subprocess so library interactions in the parent cannot touch it.
Key arrives via inherited environment (parent loads interviewiq_agent/.env).
Bytes in/out (UTF-8) — Windows console encoding must never see this stream.
"""

import os
import sys

MODEL = "gemini-3.5-flash-lite"


def main() -> None:
    from google import genai

    text = sys.stdin.read()
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    resp = client.models.generate_content(
        model=MODEL,
        contents=(
            "Translate the following video transcript part to English. Keep "
            "technical terms, names, and numbers intact. Return ONLY the "
            "translation:\n" + text
        ),
    )
    out = (resp.text or "").strip()
    if not out:
        raise RuntimeError("translation came back empty")
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))


if __name__ == "__main__":
    main()
