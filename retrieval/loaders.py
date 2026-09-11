from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_core.documents import Document


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

# docs=load_document(r"C:\Users\Hamza\Downloads\Fake_Vendor_Agreement_ContractGuard.pdf")
# print(len(docs))
# print(docs[0].page_content)