"""Embedding provider abstraction.

`EMBEDDING_PROVIDER=mock` (default) uses a deterministic hashed bag-of-words
embedding: it is a real, reproducible vector space (so pgvector search, ranking
and the whole RAG path are exercised end-to-end without an API key), but it
captures lexical overlap rather than true semantics — the API reports
`provider="mock"` so nobody mistakes its recall for a semantic model's.

Production: `openai` (text-embedding-3-*) or `sentence_transformers`
(multilingual Indic models) — see docs/rag.md for model selection notes.

Dimension consistency is enforced: the provider's dimension must equal
EMBEDDING_DIM, because pgvector columns are typed `vector(n)`.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.core.errors import ProviderUnavailableError

_TOKEN_RE = re.compile(r"[a-zA-Z0-9\u0900-\u097F]+")


@dataclass(slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model: str
    is_demo: bool
    dimension: int
    version: str = "1"
    usage_tokens: int | None = None
    notices: list[str] = field(default_factory=list)


class EmbeddingProvider(Protocol):
    name: str
    is_demo: bool
    model: str
    dimension: int
    version: str

    def embed(
        self, texts: list[str], *, input_type: str = "document"
    ) -> EmbeddingResult: ...

    def health(self) -> dict[str, Any]: ...


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class MockEmbeddingProvider:
    """Deterministic hashed bag-of-words vectors, L2-normalised.

    * same text ⇒ same vector (stable across processes, no model file needed);
    * unigrams, bigrams and character trigrams are hashed into the configured
      dimension, which gives useful fuzzy matching for the demo dataset;
    * the API labels both the model (`mock-hash-embedding-v1`) and the fact that
      it is a demo provider, and `uses_semantic_model=False` is reported by
      /api/v1/knowledge/health so quality claims stay honest.
    """

    name = "mock"
    is_demo = True
    model = "mock-hash-embedding-v1"
    version = "1"
    uses_semantic_model = False

    def __init__(self, dimension: int | None = None) -> None:
        self.dimension = dimension or settings.embedding_dim

    def _hash_index(self, token: str, salt: str) -> tuple[int, float]:
        digest = hashlib.blake2b(f"{salt}:{token}".encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % self.dimension
        sign = 1.0 if (value >> 63) & 1 else -1.0
        return index, sign

    def embed(
        self, texts: list[str], *, input_type: str = "document"
    ) -> EmbeddingResult:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            tokens = _tokenize(text)
            features: list[tuple[str, float]] = []
            for token in tokens:
                features.append((token, 1.0))
                if len(token) >= 4:
                    features.extend(
                        (token[i : i + 3], 0.35) for i in range(len(token) - 2)
                    )
            for first, second in zip(tokens, tokens[1:]):
                features.append((f"{first}_{second}", 0.7))
            for feature, weight in features:
                index, sign = self._hash_index(feature, "v1")
                vector[index] += sign * weight
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            vectors.append([round(v / norm, 6) for v in vector])
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=self.model,
            is_demo=True,
            dimension=self.dimension,
            version=self.version,
            notices=[
                "Demo embedding provider: lexical (hashed n-gram) vectors, not a trained semantic model."
            ],
        )

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": True,
            "is_demo": True,
            "model": self.model,
            "dimension": self.dimension,
            "uses_semantic_model": False,
        }


class OpenAIEmbeddingProvider:
    name = "openai"
    is_demo = False
    version = "1"

    def __init__(self) -> None:
        self.api_key = settings.embedding_api_key
        self.base_url = (settings.llm_base_url or "https://api.openai.com/v1").rstrip(
            "/"
        )
        self.model = (
            settings.embedding_model
            if settings.embedding_model != "mock-hash-embedding-v1"
            else "text-embedding-3-small"
        )
        self.dimension = settings.embedding_dim

    def embed(
        self, texts: list[str], *, input_type: str = "document"
    ) -> EmbeddingResult:
        if not self.api_key:
            raise ProviderUnavailableError(
                "Semantic search is not configured on this deployment.",
                details={"provider": self.name, "missing": ["EMBEDDING_API_KEY"]},
            )
        try:
            response = httpx.post(
                f"{self.base_url}/embeddings",
                json={
                    "model": self.model,
                    "input": texts,
                    "dimensions": self.dimension,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "The embedding service could not be reached.",
                details={"provider": self.name},
            ) from exc
        payload = response.json()
        vectors = [item["embedding"] for item in payload.get("data", [])]
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=self.model,
            is_demo=False,
            dimension=self.dimension,
            version=self.version,
            usage_tokens=payload.get("usage", {}).get("total_tokens"),
        )

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "available": bool(self.api_key),
            "is_demo": False,
            "model": self.model,
            "dimension": self.dimension,
            "uses_semantic_model": True,
        }


class SentenceTransformerProvider:
    """Local multilingual model (no API key, runs on CPU).

    Loaded lazily and cached in-process; the model file is downloaded on first
    use, so this provider reports itself unavailable until the dependency and
    weights are present rather than failing mid-request.
    """

    name = "sentence_transformers"
    is_demo = False
    version = "1"

    def __init__(self) -> None:
        self.model_name = (
            settings.embedding_model
            if settings.embedding_model != "mock-hash-embedding-v1"
            else "paraphrase-multilingual-MiniLM-L12-v2"
        )
        self.dimension = settings.embedding_dim
        self._model: Any = None
        self._load_error: str | None = None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self.model_name)
            self.dimension = int(self._model.get_sentence_embedding_dimension())
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)[:200]
            raise ProviderUnavailableError(
                "The local embedding model is not available on this deployment.",
                details={
                    "provider": self.name,
                    "model": self.model_name,
                    "detail": self._load_error,
                },
            ) from exc
        return self._model

    def embed(
        self, texts: list[str], *, input_type: str = "document"
    ) -> EmbeddingResult:
        model = self._load()
        vectors = [
            list(map(float, v)) for v in model.encode(texts, normalize_embeddings=True)
        ]
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=self.model_name,
            is_demo=False,
            dimension=self.dimension,
            version=self.version,
        )

    def health(self) -> dict[str, Any]:
        try:
            self._load()
            available = True
            detail = None
        except ProviderUnavailableError as exc:
            available = False
            detail = str(exc.details.get("detail") or exc.message)
        return {
            "provider": self.name,
            "available": available,
            "is_demo": False,
            "model": self.model_name,
            "dimension": self.dimension,
            "detail": detail,
        }


def get_embedding_provider() -> EmbeddingProvider:
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingProvider()
    if settings.embedding_provider == "sentence_transformers":
        return SentenceTransformerProvider()
    return MockEmbeddingProvider()
