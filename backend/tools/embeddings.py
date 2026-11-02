"""Swappable embeddings module for VouchFlow AI Contract RAG.
Defaults to local ONNX all-MiniLM-L6-v2 via ChromaDB (100% offline, free, no quota limits).
Can be easily swapped to other providers (Google GenAI, HuggingFace, etc.) via configuration.
"""
from typing import List, Optional
import os
from langchain_core.embeddings import Embeddings


class ChromaDefaultEmbeddings(Embeddings):
    """Wraps ChromaDB's built-in ONNX all-MiniLM-L6-v2 embedding function
    into LangChain's Embeddings interface.
    """
    def __init__(self):
        from chromadb.utils import embedding_functions
        self._ef = embedding_functions.DefaultEmbeddingFunction()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of contract chunks."""
        if not texts:
            return []
        raw_embeddings = self._ef(texts)
        # Ensure list of float lists
        return [list(map(float, emb)) for emb in raw_embeddings]

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string."""
        raw_embedding = self._ef([text])[0]
        return list(map(float, raw_embedding))


def get_embedding_model(provider: Optional[str] = None) -> Embeddings:
    """Factory function returning the configured Embeddings instance.
    Defaults to local ONNX embeddings ('local' / 'chroma_default').
    To swap, pass provider='google_genai' or configure via EMBEDDING_PROVIDER in .env.
    """
    prov = provider or os.getenv("EMBEDDING_PROVIDER", "local").lower()
    
    if prov in ("local", "chroma", "chroma_default", "minilm"):
        return ChromaDefaultEmbeddings()
    
    elif prov in ("gemini", "google", "google_genai"):
        # Swappable to Google GenAI embeddings if explicitly enabled
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        api_key = os.getenv("GEMINI_API_KEY")
        return GoogleGenerativeAIEmbeddings(model="models/text-embedding-004", google_api_key=api_key)
    
    else:
        # Fallback to local default
        return ChromaDefaultEmbeddings()
