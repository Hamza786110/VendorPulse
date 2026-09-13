import os
from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.documents import Document
load_dotenv()

def get_embedding_model() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=os.environ.get("GOOGLE_API_KEY"),  # type: ignore
    )


def embed_chunks(chunks: list[Document]) -> list[list[float]]:
    """Turns chunk text into vectors. This IS the embedding step."""
    model = get_embedding_model()
    texts = [chunk.page_content for chunk in chunks]
    return model.embed_documents(texts)


def embed_query(question: str) -> list[float]:
    """Embeds a single question string, for similarity search later."""
    model = get_embedding_model()
    return model.embed_query(question)