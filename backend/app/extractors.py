"""Turn uploaded files (TXT, MD, CSV, PDF, images) into plain text."""
import csv
import io
import os

from . import llm

IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
TEXT_EXT = {".txt", ".md", ".markdown", ".text"}

OCR_INSTRUCTION = (
    "Read this image carefully. Transcribe ALL text in it exactly as written, keeping the order and "
    "structure (headings, lists, tables). If it contains diagrams, charts, formulas or handwriting, "
    "also describe their key content briefly. Output only the extracted content, with no commentary."
)


class ExtractError(Exception):
    """A file could not be read; the message is safe to show the user."""


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _csv_to_text(data: bytes) -> str:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(text), dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""
    header, body = rows[0], rows[1:]
    if not body:
        return " | ".join(header)
    lines = []
    for row in body:
        pairs = [
            f"{header[i].strip() if i < len(header) and header[i].strip() else f'col{i + 1}'}: {cell.strip()}"
            for i, cell in enumerate(row)
            if cell.strip()
        ]
        if pairs:
            lines.append(" | ".join(pairs))
    return "\n".join(lines)


async def _pdf_to_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        raise ExtractError("PDF support is not installed on the server (pip install pypdf).")

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            if not reader.decrypt(""):
                raise ExtractError("This PDF is password-protected.")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except ExtractError:
        raise
    except PdfReadError:
        raise ExtractError("This PDF could not be read (it may be corrupted).")

    text = "\n\n".join(p for p in pages if p)
    if len(text.strip()) >= 10 * max(1, len(pages)):  # has a real text layer
        return text

    # Scanned PDF: render each page to an image and read it with the vision model.
    return await _scanned_pdf_to_text(data)


async def _scanned_pdf_to_text(data: bytes) -> str:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise ExtractError(
            "This PDF looks scanned (no selectable text). Upload its pages as images instead, "
            "or install pypdfium2 on the server to read scanned PDFs."
        )
    pdf = pdfium.PdfDocument(data)
    parts = []
    for i in range(len(pdf)):
        bitmap = pdf[i].render(scale=2).to_pil()
        buf = io.BytesIO()
        bitmap.save(buf, format="PNG")
        page_text = await llm.describe_image(buf.getvalue(), "image/png", OCR_INSTRUCTION)
        if page_text.strip():
            parts.append(page_text.strip())
    return "\n\n".join(parts)


async def extract(filename: str, data: bytes, content_type: str = "") -> str:
    """Return the text content of an uploaded file."""
    ext = os.path.splitext(filename or "")[1].lower()
    content_type = (content_type or "").lower()

    if ext == ".pdf" or content_type == "application/pdf":
        text = await _pdf_to_text(data)
    elif ext in IMAGE_EXT or content_type.startswith("image/"):
        mime = IMAGE_EXT.get(ext) or content_type or "image/png"
        text = await llm.describe_image(data, mime, OCR_INSTRUCTION)
    elif ext == ".csv" or content_type in ("text/csv", "application/csv"):
        text = _csv_to_text(data)
    elif ext in TEXT_EXT or content_type.startswith("text/"):
        text = _decode(data)
    else:
        raise ExtractError(f"Unsupported file type '{ext or content_type or 'unknown'}'. Use PDF, TXT, MD, CSV or an image.")

    text = text.strip()
    if not text:
        raise ExtractError("No readable text was found in this file.")
    return text
