"""PDF report builder — pure function, no AI, no network.

Latin-1 note: core Helvetica covers latin-1 only, so text is sanitized
(em-dash/bullets mapped) instead of embedding a font (keeps image lean).

Content parity with the web report is the point of this module: the page shows
strengths / gaps / study-next / verdict / verdict-why, so the download must
too — a PDF that carries only the scoreboard is the least useful artefact of
the three (page, JSON, PDF).
"""

_CLEAN = {"—": "-", "–": "-", "•": "*", "“": '"', "”": '"', "’": "'", "…": "..."}

# Mirrors the web report (frontend/components/ReportView.tsx:26-36): a stored
# verdict wins when it is one of these three, otherwise `overall` decides.
# Guarded by tests/test_units.py::test_pdf_verdict_falls_back_to_thresholds.
_VERDICTS = ("Strong Hire", "Hire", "No Hire")


def _clean(text: str) -> str:
    for src, dst in _CLEAN.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _verdict(report: dict) -> str:
    """Stored verdict if it is a real one, else the page's threshold rule."""
    stored = (report.get("verdict") or "").strip()
    if stored in _VERDICTS:
        return stored
    try:
        overall = float(report.get("overall") or 0.0)
    except (TypeError, ValueError):
        overall = 0.0
    if overall >= 7.5:
        return "Strong Hire"
    if overall >= 5.0:
        return "Hire"
    return "No Hire"


def report_sections(report: dict) -> list[tuple[str, str]]:
    """Qualitative blocks in print order; blank bodies are dropped entirely.

    Legacy docs without enrichment therefore render a clean PDF instead of a
    stack of empty headings. The transcript deliberately comes AFTER these:
    a reader wants the verdict and takeaways first, the evidence second.
    """
    return [
        (heading, body)
        for heading, body in (
            ("Why this verdict", report.get("verdict_why", "")),
            ("Strengths", report.get("strengths", "")),
            ("Gaps to close", report.get("gaps", "")),
            ("Study next", report.get("study_next", "")),
        )
        if (body or "").strip()
    ]


def build_report_pdf(report: dict, turns: list[dict]) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF()
    pdf.set_auto_page_break(True, 20)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(0, 12, "InterviewIQ Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, f"Session: {report.get('session_id', '')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Overall: {report.get('overall', 0.0)} / 10", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Verdict: {_clean(_verdict(report))}", new_x="LMARGIN", new_y="NEXT")
    if report.get("adjustment"):
        pdf.cell(0, 8, f"Adjustment: {_clean(str(report['adjustment']))}",
                 new_x="LMARGIN", new_y="NEXT")

    for heading, body in report_sections(report):
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, _clean(heading), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 6, _clean(str(body)), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Per-question breakdown", new_x="LMARGIN", new_y="NEXT")
    per = report.get("per_question", [])
    for i, t in enumerate(turns):
        score = per[i] if i < len(per) else t.get("score", 0.0)
        pdf.set_font("Helvetica", "B", 12)
        pdf.multi_cell(0, 8, f"Q{i + 1}: {_clean(str(t.get('q', '')))[:200]}",
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 11)
        pdf.multi_cell(0, 7, f"Score: {score}/10",
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.multi_cell(0, 7, f"A: {_clean(str(t.get('a', '')))[:500]}",
                       new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
    return bytes(pdf.output())
