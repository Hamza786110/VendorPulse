"""
contracts/utils.py

File handling helpers: save an uploaded file to disk, extract raw text
from PDF/DOCX so the extraction chain has something to read.
"""

import os
import uuid
from pathlib import Path

from fastapi import UploadFile
import pdfplumber
import docx  # python-docx

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".docx"}


async def save_upload(file: UploadFile) -> tuple[str, str]:
    """
    Saves the uploaded file to disk under a UUID-prefixed name to avoid
    collisions. Returns (contract_id, saved_file_path).
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS}")

    contract_id = str(uuid.uuid4())
    dest_path = UPLOAD_DIR / f"{contract_id}{ext}"

    content = await file.read()
    dest_path.write_bytes(content)

    return contract_id, str(dest_path)


def extract_text_from_file(file_path: str) -> str:
    """Pulls raw text out of a PDF or DOCX file for the LLM to read."""
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        text_chunks = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_chunks.append(page_text)
        return "\n".join(text_chunks)

    if ext == ".docx":
        d = docx.Document(file_path)
        return "\n".join(p.text for p in d.paragraphs if p.text)

    raise ValueError(f"Unsupported file type '{ext}' for text extraction.")