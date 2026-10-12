"""Transforme une lettre de motivation texte/Markdown simple en PDF A4 propre.

  python make_letter_pdf.py lettre.md [-o lettre.pdf]

Les paragraphes sont séparés par une ligne vide. **gras** est accepté. Un bloc dont toutes les
lignes commencent par « > » est aligné à droite (destinataire, lieu et date). Nécessite reportlab.
"""
import argparse
import html
import re
import sys
from pathlib import Path

try:
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
except ImportError:
    sys.exit("reportlab manquant : pip install reportlab")

FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]


def register_font():
    for regular, bold in FONT_CANDIDATES:
        if Path(regular).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("Body", regular))
            pdfmetrics.registerFont(TTFont("Body-Bold", bold))
            pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold")
            return "Body"
    return "Helvetica"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("-o", "--output")
    a = ap.parse_args()
    src = Path(a.source)
    out = Path(a.output) if a.output else src.with_suffix(".pdf")

    font = register_font()
    style = ParagraphStyle("body", fontName=font, fontSize=11, leading=15.5, spaceAfter=8)
    right = ParagraphStyle("right", parent=style, alignment=TA_RIGHT)
    story = []
    for block in re.split(r"\n\s*\n", src.read_text(encoding="utf-8").strip()):
        block = re.sub(r"^#+\s*", "", block.strip())
        lines = block.splitlines()
        is_right = all(line.lstrip().startswith(">") for line in lines)
        if is_right:
            block = "\n".join(re.sub(r"^\s*>\s?", "", line) for line in lines)
        text = html.escape(block)
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text).replace("\n", "<br/>")
        story += [Paragraph(text, right if is_right else style), Spacer(1, 2)]

    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=2.3 * cm, rightMargin=2.3 * cm,
                      topMargin=2.2 * cm, bottomMargin=2.2 * cm, title="Lettre de motivation").build(story)
    print(out)


if __name__ == "__main__":
    main()
