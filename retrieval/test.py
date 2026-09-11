from loaders import load_document
from chunking import chunk_documents

docs=load_document(r"C:\Users\Hamza\Downloads\Fake_Vendor_Agreement_ContractGuard.pdf")

print(len(docs))
# print(docs[0].page_content)
print("\n\n\n")
chunked_docs=chunk_documents(docs=docs)
print(len(chunked_docs))
print(type(chunked_docs))
# print(chunked_docs[0].page_content)

for chnk in chunked_docs:
    print("Chunk content:", chnk.page_content)
    print("Chunk metadata:", chnk.metadata)
    print("\n\n\n")