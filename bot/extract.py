"""Text extraction from PDF (including scans via OCR), DOCX and TXT."""

import io
import logging
import re

import docx
import fitz  # PyMuPDF
import pytesseract
from PIL import Image, ImageChops

log = logging.getLogger(__name__)

SUPPORTED = (".pdf", ".docx", ".txt")
OCR_LANG = "ukr+eng"  # with eng, the digit 3 is not confused with the Cyrillic letter З
MIN_PAGE_TEXT = 20
OCR_THRESHOLD = 90


class UnsupportedFormat(Exception):
    pass


def extract_text(data: bytes, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        text = _pdf(data)
    elif name.endswith(".docx"):
        text = _docx(data)
    elif name.endswith(".txt"):
        text = _txt(data)
    else:
        raise UnsupportedFormat(filename)
    return _clean(text)


def _pdf(data: bytes) -> str:
    pages = []
    with fitz.open(stream=data, filetype="pdf") as pdf:
        for page in pdf:
            text = page.get_text()
            if len(text.strip()) < MIN_PAGE_TEXT:
                # A page without a text layer is a scan: recognise the image.
                text = _ocr(page)
            pages.append(text)
    return "\n".join(pages)


def _ocr(page: fitz.Page) -> str:
    pix = page.get_pixmap(dpi=300)
    red, green, blue = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).split()
    # Text is black while background stains (birch bark) are brown: only one or two of their channels are dark.
    # So a pixel counts as text only if ALL channels are dark: stains vanish, digits stay intact.
    brightest = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    binary = brightest.point(lambda x: 255 if x > OCR_THRESHOLD else 0)
    raw = pytesseract.image_to_string(binary, lang=OCR_LANG, config="--psm 4")
    return "\n".join(line for line in raw.splitlines() if _is_text_line(line))


def _is_text_line(line: str) -> bool:
    """Drops junk lines from background stains: a real line has at least one word of 3+ letters."""
    return bool(re.search(r"[А-Яа-яЇїІіЄєҐґA-Za-z]{3,}", line)) or not line.strip()


def _docx(data: bytes) -> str:
    document = docx.Document(io.BytesIO(data))
    lines = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(lines)


def _txt(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    text = text.replace("\r", "").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()
