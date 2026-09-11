from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document


def chunk_documents(docs: list[Document],chunk_size: int = 800,chunk_overlap: int = 150,) -> list[Document]:
    """
    Splits a list of Documents into smaller chunked Documents,
    preserving original metadata (e.g. page number, source file).
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return splitter.split_documents(docs)

