import chromadb
from langchain_core.documents import Document

from embeddings import embed_chunks, embed_query

CHROMA_PERSIST_DIR = "./chroma_db"
COLLECTION_NAME = "contracts"


def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
    return client.get_or_create_collection(name=COLLECTION_NAME)


def _clean_metadata(meta: dict) -> dict:
    """Chroma rejects None values in metadata, so strip them out."""
    cleaned={}
    for k, v in meta.items():
        if v is not None:
            cleaned[k]=v
    return cleaned


def store_chunks(chunks: list[Document], contract_id: str) -> list[str]:
    """
    1. Calls embeddings.py to turn chunk text into vectors
    2. Stores vectors + original text + metadata in Chroma
    Explicit ids mean re-running this for the same contract_id
    overwrites instead of duplicating.
    """
    vectors = embed_chunks(chunks)  # <-- the embedding step, from the other file
    texts = [c.page_content for c in chunks]
    ids=[]
    for i in range(len(chunks)):
        ids.append(f"{contract_id}-{i}")
    metadatas = []
    for i, chunk in enumerate(chunks):
        meta = _clean_metadata(dict(chunk.metadata))
        meta["contract_id"] = contract_id
        meta["chunk_index"] = i
        metadatas.append(meta)

    collection = get_collection()
    collection.upsert(ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas)
    return ids


def query_contract(contract_id: str, question: str, k: int = 4):
    """Embeds the question, then searches for the top-k closest chunks for one contract."""
    query_vector = embed_query(question)  # <-- embedding step again, same source

    collection = get_collection()
    return collection.query(
        query_embeddings=[query_vector],
        n_results=k,
        where={"contract_id": contract_id},
    )


def delete_contract_chunks(contract_id: str) -> None:
    collection = get_collection()
    collection.delete(where={"contract_id": contract_id})