"""PDF report builder — pure function, no AI, no network.

Latin-1 note: core Helvetica covers latin-1 only, so text is sanitized
(em-dash/bullets mapped) instead of embedding a font (keeps image lean).
"""

_CLEAN = {"—": "-", "–": "-", "•": "*", "“": '"', "”": '"', "’": "'", "…": "..."}


def _clean(text: str) -> str:
    for src, dst in _CLEAN.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


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
    if report.get("adjustment"):
        pdf.cell(0, 8, f"Adjustment: {_clean(report['adjustment'])}", new_x="LMARGIN", new_y="NEXT")
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
