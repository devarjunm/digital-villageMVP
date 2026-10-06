"""Optional reranking stage.

No cross-encoder is bundled (it would require model weights and a licence review
per model). Instead this module provides:

  * `LexicalReranker` — a deterministic BM25-style rescoring over the retrieved
    candidates that combines the vector similarity with lexical overlap and
    metadata matches. It is always available and improves ordering when queries
    contain exact terms, crop names or place names.
  * `CrossEncoderReranker` — interface-complete hook that activates only when a
    reranker model is configured (`RERANKER_MODEL`); otherwise it degrades to
    the lexical reranker and says so in the response metadata.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.core.config import settings

_TOKEN_RE = re.compile(r"[a-zA-Z0-9\u0900-\u097F]+")


@dataclass(slots=True)
class Candidate:
    id: str
    text: str
    vector_score: float
    metadata: dict


@dataclass(slots=True)
class RankedCandidate:
    candidate: Candidate
    score: float
    components: dict[str, float]


class LexicalReranker:
    name = "lexical_bm25"
    is_model_backed = False

    def __init__(
        self, *, k1: float = 1.4, b: float = 0.72, weight: float = 0.35
    ) -> None:
        self.k1 = k1
        self.b = b
        self.lexical_weight = weight

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [t.lower() for t in _TOKEN_RE.findall(text)]

    def rerank(
        self,
        *,
        query: str,
        candidates: list[Candidate],
        top_k: int = 6,
        metadata_filters: dict | None = None,
    ) -> list[RankedCandidate]:
        if not candidates:
            return []
        q_terms = self._tokens(query)
        doc_tokens = [self._tokens(c.text) for c in candidates]
        lengths = [len(t) or 1 for t in doc_tokens]
        avg_len = sum(lengths) / len(lengths)
        df = Counter()
        for tokens in doc_tokens:
            for term in set(tokens):
                df[term] += 1
        total_docs = len(candidates)
        filters = metadata_filters or {}

        ranked: list[RankedCandidate] = []
        for candidate, tokens, length in zip(candidates, doc_tokens, lengths):
            idf_sum = 0.0
            tf_sum = 0.0
            freq = Counter(tokens)
            for term in set(q_terms):
                if term not in freq:
                    continue
                idf = math.log(1 + (total_docs - df[term] + 0.5) / (df[term] + 0.5))
                tf = (
                    freq[term]
                    * (self.k1 + 1)
                    / (freq[term] + self.k1 * (1 - self.b + self.b * length / avg_len))
                )
                idf_sum += idf
                tf_sum += idf * tf
            lexical = tf_sum / (idf_sum + 1e-6) if idf_sum else 0.0
            boost = 0.0
            for key, wanted in filters.items():
                if not wanted:
                    continue
                actual = candidate.metadata.get(key)
                if actual is None:
                    continue
                values = wanted if isinstance(wanted, (list, tuple, set)) else [wanted]
                if any(str(v).lower() == str(actual).lower() for v in values):
                    boost += 0.05
                if key == "crop_code" and str(actual).lower() == str(wanted).lower():
                    boost += 0.05
            score = (
                (1 - self.lexical_weight) * candidate.vector_score
                + self.lexical_weight * lexical
                + min(boost, 0.15)
            )
            ranked.append(
                RankedCandidate(
                    candidate=candidate,
                    score=round(score, 6),
                    components={
                        "vector": round(candidate.vector_score, 6),
                        "lexical": round(lexical, 6),
                        "metadata_boost": round(boost, 6),
                    },
                )
            )
        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked[:top_k]


class CrossEncoderReranker:
    """Placeholder for a real cross-encoder; activates with RERANKER_MODEL set."""

    name = "cross_encoder"
    is_model_backed = True

    def __init__(self) -> None:
        self.model_name = settings.reranker_model
        self._model = None

    def available(self) -> bool:
        return bool(self.model_name)

    def rerank(
        self,
        *,
        query: str,
        candidates: list[Candidate],
        top_k: int = 6,
        metadata_filters: dict | None = None,
    ):
        if not self.available():
            return LexicalReranker().rerank(
                query=query,
                candidates=candidates,
                top_k=top_k,
                metadata_filters=metadata_filters,
            )
        raise NotImplementedError(
            "Configure RERANKER_MODEL and implement the scoring call for your chosen cross-encoder."
        )


def get_reranker():
    """Returns the active reranker. Lexical by default, and the response
    metadata always names which one ran."""
    cross_encoder = CrossEncoderReranker()
    if cross_encoder.available():
        return cross_encoder
    return LexicalReranker()
