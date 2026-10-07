from datetime import date
from pathlib import Path

from fpdf import FPDF

from app.schemas import Recipient


def render_certificate(recipient: Recipient, title: str, output_path: Path) -> None:
    """Render the single predefined certificate template to a PDF at output_path.

    Uses the built-in Helvetica font, so text must be Latin-1 encodable; anything else
    raises and is recorded as a failure for that one certificate.
    """
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    w, h = pdf.w, pdf.h

    pdf.set_draw_color(30, 58, 138)
    pdf.set_line_width(2)
    pdf.rect(8, 8, w - 16, h - 16)
    pdf.set_line_width(0.5)
    pdf.rect(12, 12, w - 24, h - 24)

    def line(text: str, size: int, style: str, y: float, color=(30, 30, 30)) -> None:
        pdf.set_font("Helvetica", style, size)
        pdf.set_text_color(*color)
        pdf.set_xy(0, y)
        pdf.cell(w, 12, text, align="C")

    line("CERTIFICATE", 40, "B", 35, (30, 58, 138))
    line("OF COMPLETION", 18, "", 52)
    line("This is proudly presented to", 14, "I", 78)
    line(recipient.name, 32, "B", 92)
    line("for successfully completing", 14, "I", 115)
    line(recipient.course or title, 22, "B", 128)
    if recipient.course:
        line(title, 14, "", 143)
    issued = recipient.issue_date or date.today()
    line(f"Issued on {issued.strftime('%d %B %Y')}", 12, "", 170)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
