"""Extract plain text from an uploaded resume file (PDF or DOCX).

Pure parsing, no LLM. Kept deliberately small: the caller (server.py) owns the
HTTP-level guards (size cap, content-type) and turns anything raised here into a
friendly 400 — never a 500.
"""
import io

# Minimum characters of real text we expect from a genuine resume. Below this we
# assume the file was image-only / scanned (no embedded text layer) and tell the
# user to paste instead.
_MIN_TEXT_LEN = 20


class ResumeParseError(Exception):
    """Raised when a file can't be parsed or yields no usable text."""


def extract_text(filename: str, data: bytes) -> str:
    """Return extracted text for a PDF or DOCX file.

    Raises ResumeParseError (with a user-friendly message) on an unsupported
    type, a corrupt/unreadable file, or when extraction yields no real text.
    """
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        text = _extract_pdf(data)
    elif name.endswith(".docx"):
        text = _extract_docx(data)
    else:
        raise ResumeParseError("Unsupported file type — upload a PDF or DOCX")

    text = text.strip()
    if len(text) < _MIN_TEXT_LEN:
        raise ResumeParseError(
            "Couldn't read text from this file — it may be a scanned or "
            "image-only PDF. Paste your CV instead."
        )
    return text


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except ResumeParseError:
        raise
    except Exception as exc:  # noqa: BLE001 — surface anything as a friendly error
        raise ResumeParseError("Couldn't read this PDF. Try re-exporting it or paste the text.") from exc
    return "\n".join(pages)


def _extract_docx(data: bytes) -> str:
    from docx import Document

    try:
        doc = Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text]
    except Exception as exc:  # noqa: BLE001
        raise ResumeParseError("Couldn't read this DOCX. Try re-saving it or paste the text.") from exc
    return "\n".join(paragraphs)
