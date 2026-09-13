from langchain_core.documents import Document
import os
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_experimental.text_splitter import SemanticChunker
from embeddings import get_embedding_model
from dotenv import load_dotenv
load_dotenv()

def get_chat_model() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(model="gemini-3.8-flash")


def get_embedding_model() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=os.environ.get("GOOGLE_API_KEY") #type:ignore
    )


def chunk_documents(docs: list[Document]) -> list[Document]:
    """
    Splits Documents into chunks at points where sentence-level
    meaning shifts, using cosine similarity between embeddings.
    """
    embeddings = get_embedding_model()

    splitter = SemanticChunker(
        embeddings=embeddings,
        breakpoint_threshold_type="percentile",
    )

    return splitter.split_documents(docs)