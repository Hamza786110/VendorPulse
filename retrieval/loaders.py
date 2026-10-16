from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader# type: ignore
from langchain_core.documents import Document# type: ignore


def load_document(file_path: str) -> list[Document]:
    """
    Dispatches to the correct LangChain loader based on file extension.
    Returns a list of Document objects (unchunked, raw page/file content).
    """
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
    elif ext == ".docx":
        loader = Docx2txtLoader(file_path)
    else:
        raise ValueError(f"Unsupported file type for RAG ingestion: {ext}")

    return loader.load()
