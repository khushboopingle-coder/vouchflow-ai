"""
A tiny, instant stand-in for the ONNX embedding model, for tests.

Bag-of-words hashing into 384 dimensions (the size of the real all-MiniLM-L6-v2 vectors, so it
also fits an index that was built with the real model), normalised and scaled down. Similar
wording gives close vectors. It is good enough to test WHICH workspace finds a clause, not to
judge ranking quality - the contract-search evaluation tests keep using the real model.

This module has NO side effects (it sets no environment variables), so a subprocess can import it.
"""

import re
import zlib

from langchain_core.embeddings import Embeddings


class FakeEmbeddings(Embeddings):
    DIM = 384
    # Vectors are scaled down so every distance is small: a short question and a long clause
    # are otherwise "far apart" and would fail the real relevance threshold (1.15).
    SCALE = 0.55

    def _vector(self, text: str):
        vec = [0.0] * self.DIM
        for token in re.findall(r"[a-z0-9]+", (text or "").lower()):
            vec[zlib.crc32(token.encode()) % self.DIM] += 1.0
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [self.SCALE * x / norm for x in vec]

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)
