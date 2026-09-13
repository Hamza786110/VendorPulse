"""
retrieval/test.py

Manual pipeline test — run this to SEE each stage of the RAG ingestion
pipeline separately: raw docs -> chunked docs -> embeddings -> stored in Chroma.
"""

from loaders import load_document
from chunking import chunk_documents
from embeddings import embed_chunks
from vectorstore import store_chunks, query_contract

FILE_PATH = r"C:\Users\Hamza\Downloads\Fake_Vendor_Agreement_ContractGuard.pdf"
TEST_CONTRACT_ID = "test-contract-001"

# ---------- STAGE 1: raw docs (loaders.py) ----------
print("=" * 60)
print("STAGE 1: RAW DOCUMENTS (from loaders.py)")
print("=" * 60)

docs = load_document(FILE_PATH)
print(f"Loaded {len(docs)} raw document(s)\n")

for i, doc in enumerate(docs):
    print(f"--- Raw doc {i} ---")
    print("Content preview:", doc.page_content[:200])
    print("Metadata:", doc.metadata)
    print()

# ---------- STAGE 2: chunked docs (chunking.py) ----------
print("=" * 60)
print("STAGE 2: CHUNKED DOCUMENTS (from chunking.py)")
print("=" * 60)

chunked_docs = chunk_documents(docs=docs)
print(f"Split into {len(chunked_docs)} chunks\n")

for i, chunk in enumerate(chunked_docs):
    print(f"--- Chunk {i} ---")
    print("Content:", chunk.page_content[:200])
    print("Metadata:", chunk.metadata)
    print()

# ---------- STAGE 3: embeddings (embeddings.py) ----------
print("=" * 60)
print("STAGE 3: EMBEDDINGS (from embeddings.py)")
print("=" * 60)

vectors = embed_chunks(chunked_docs)
print(f"Generated {len(vectors)} vectors (should match {len(chunked_docs)} chunks)\n")

for i, vector in enumerate(vectors):
    print(f"--- Vector {i} (for chunk {i}) ---")
    print("Vector length (dimensions):", len(vector))
    print("First 5 values:", vector[:5])
    print()

# ---------- STAGE 4: storing in Chroma (vectorstore.py) ----------
print("=" * 60)
print("STAGE 4: STORING IN CHROMADB (from vectorstore.py)")
print("=" * 60)

# Note: this calls embed_chunks() again internally — that's expected,
# store_chunks() owns its own embedding call so it works standalone
# from anywhere in the codebase, not just from this test script.
stored_ids = store_chunks(chunked_docs, TEST_CONTRACT_ID)
print(f"Stored {len(stored_ids)} chunks under contract_id='{TEST_CONTRACT_ID}'")
print("IDs:", stored_ids, "\n")

# ---------- STAGE 5: querying back (sanity check) ----------
print("=" * 60)
print("STAGE 5: QUERY TEST (retrieval sanity check)")
print("=" * 60)

question = "when does this contract renew?"
results = query_contract(TEST_CONTRACT_ID, question)

print(f"Question: {question}\n")

for doc_text, dist in zip(results["documents"][0], results["distances"][0]):
       print(f"Match (distance={dist:.4f}):", doc_text[:200])
       print()
