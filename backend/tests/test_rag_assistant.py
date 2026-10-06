"""Retrieval-augmented answering: `/knowledge/ask` and `/knowledge/retrieve`.

Why this file exists: neither endpoint had a single test, and the flagship
"ask the assistant" path was completely broken on PostgreSQL. The vector-search
SQL filtered regional documents with `json_array_length(d.state_codes)` — a
function that does not exist for a jsonb column (the correct name is
`jsonb_array_length`). PostgreSQL raised `UndefinedFunction`, the API mapped it
to `500 database_unavailable`, and because the farm's state is applied
automatically as retrieval context, *every* answer request from a farmer with a
known state failed. `/knowledge/retrieve` looked healthy only because it was
being called without filters.

These tests pin the contract the Flutter assistant screen renders:
a real answer, real citations, and no claim without a source.
"""

from __future__ import annotations

import uuid

import pytest

# A short, clearly-labelled test document. It is inserted by the test itself and
# never touches demo or production reference data.
DOC_TITLE = "Test-only advisory: nitrogen split application in onion"
DOC_BODY = (
    "Nitrogen for onion is normally applied in splits rather than one dose. "
    "A common schedule is one third at transplanting, one third about thirty days "
    "later, and one third at bulb initiation. Excess nitrogen late in the season "
    "delays maturity and reduces storage life. Soil test values should decide the "
    "total quantity; this text is a test fixture, not agronomic advice."
)


def _insert_document(db, *, state_codes: list[str], crop_codes: list[str]):
    """Insert a knowledge document with one embedded chunk.

    The embedding comes from the configured provider, so the pgvector search path
    is exercised for real rather than mocked out.
    """
    from genai.embeddings.provider import get_embedding_provider

    from app.core.enums import DocumentType, Language
    from app.knowledge.models import KnowledgeChunk, KnowledgeDocument

    provider = get_embedding_provider()
    vector = provider.embed([DOC_BODY], input_type="document").vectors[0]

    document = KnowledgeDocument(
        title=DOC_TITLE,
        source_name="Digital Village test fixture",
        source_url="https://example.invalid/test-only/advisory",
        language=Language.EN,
        doc_type=DocumentType.ADVISORY,
        crop_codes=crop_codes,
        state_codes=state_codes,
        topics=["nitrogen"],
        summary="Test fixture used by the automated tests only.",
        is_demo=True,
    )
    db.add(document)
    db.flush()
    db.add(
        KnowledgeChunk(
            document_id=document.id,
            chunk_index=0,
            heading="Split application",
            content=DOC_BODY,
            token_count=len(DOC_BODY.split()),
            char_count=len(DOC_BODY),
            embedding=vector,
            embedding_model=provider.model,
            embedding_version=provider.version,
            content_hash=uuid.uuid4().hex + uuid.uuid4().hex[:32],
        )
    )
    db.flush()
    return document


def test_ask_succeeds_for_a_farmer_whose_state_filters_retrieval(client, farmer, db):
    """Regression: the state filter must not break the query.

    `farmer` has a Maharashtra profile, so the pipeline applies a state filter
    and this request used to fail with `500 database_unavailable`.
    """
    response = client.post(
        "/api/v1/knowledge/ask",
        headers=farmer.headers,
        json={"question": "How should nitrogen be applied to onion?", "top_k": 3},
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["answer"].strip()
    assert body["disclaimer"].strip()
    assert isinstance(body["citations"], list)
    assert isinstance(body["notices"], list)
    # Provider provenance must be disclosed on every answer.
    assert body["llm"]["provider"]
    assert body["llm"]["model"]
    assert "is_demo" in body["llm"]
    # The retrieval method and the fact that a demo embedder was used are visible.
    assert body["retrieval"]["method"]
    assert body["retrieval"]["embedding_provider"]


def test_ask_error_never_leaks_sql_or_credentials(client, farmer):
    """A rejected request must not echo database internals back to the client."""
    response = client.post(
        "/api/v1/knowledge/ask",
        headers=farmer.headers,
        json={"question": "", "top_k": 3},
    )
    assert response.status_code == 422
    text = response.text.lower()
    for leak in ("psycopg", "sqlalchemy", "select ", "password", "traceback"):
        assert leak not in text


def test_answer_cites_the_document_it_used(client, farmer, db):
    """Grounded answering: citations must point at the document that was retrieved.

    `citations[].ref_id` is the *chunk* id (a chunk is the retrieval unit) and the
    title carries the document title, so the app can show a source list that
    traces back to a real stored document.
    """
    document = _insert_document(db, state_codes=["Maharashtra"], crop_codes=["onion"])

    response = client.post(
        "/api/v1/knowledge/ask",
        headers=farmer.headers,
        json={
            "question": "How is nitrogen applied to onion?",
            "top_k": 5,
            "filters": {"state_codes": ["Maharashtra"]},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["citations"], "a retrieved document must appear in the citations"
    matching = [c for c in body["citations"] if c["title"].startswith(DOC_TITLE)]
    assert matching, (
        "the retrieved fixture document must be citable by its real title; "
        f"got {[c['title'][:60] for c in body['citations']]}"
    )
    citation = matching[0]
    assert citation["kind"] == "knowledge_chunk"
    assert citation["ref_id"], "a citation without an id cannot be opened in the app"
    # No fabricated links: the URL is either absent or the stored value.
    assert citation.get("source_url") in (None, "", document.source_url)


def test_retrieval_uses_the_database_index_when_it_is_available(client, farmer, db):
    """The pgvector SQL path must actually run where pgvector exists.

    `supports_pgvector()` used to be probed with `.connect()` on what the test
    suite hands it (a `Connection`, not an `Engine`). The resulting
    `AttributeError` was swallowed and reported as "pgvector unsupported", so the
    suite silently exercised only the Python fallback and never touched the SQL
    that had been broken for every state-filtered query.
    """
    from app.database.capabilities import supports_pgvector

    response = client.post(
        "/api/v1/knowledge/retrieve",
        headers=farmer.headers,
        json={"query": "onion nitrogen", "top_k": 3},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    if supports_pgvector(db.get_bind()):
        assert (
            body["index_used"] is True
        ), "this database has pgvector; retrieval must not quietly fall back"
        assert body["method"] == "pgvector_cosine"
    else:
        assert body["index_used"] is False
        assert body["method"] == "python_cosine_fallback"
    assert body["embedding_provider"]


def test_retrieve_with_state_filter_returns_chunks(client, farmer, db):
    """The retrieval endpoint honours filters and reports how it searched."""
    _insert_document(db, state_codes=["Maharashtra"], crop_codes=["onion"])

    response = client.post(
        "/api/v1/knowledge/retrieve",
        headers=farmer.headers,
        json={
            "query": "nitrogen split application onion",
            "top_k": 5,
            "filters": {"state_codes": ["Maharashtra"]},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["chunks"], "the seeded document should be retrievable by its own text"
    chunk = body["chunks"][0]
    assert chunk["content"]
    assert body["method"]
    assert isinstance(body["notices"], list)


def test_insufficient_evidence_is_admitted_not_papered_over(client, farmer):
    """With nothing relevant in the corpus the assistant must say so.

    The answer may still be extractive filler from the demo provider, but the
    API must set the flag and explain it so the app can show a warning instead of
    presenting a guess as knowledge.
    """
    response = client.post(
        "/api/v1/knowledge/ask",
        headers=farmer.headers,
        json={
            "question": "What is the exact subsidy amount for a diamond-tipped plough in 2099?",
            "top_k": 3,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    if body["insufficient_evidence"]:
        assert body[
            "insufficient_reason"
        ], "the user must be told *why* nothing was found, not just that it failed"
    else:
        # If evidence was found, it must be cited — never an uncited claim.
        assert body["citations"], "an answer presented as supported must carry citations"
        assert body["guardrails"]["grounded"] is True


@pytest.mark.parametrize("top_k", [0, -1, 999])
def test_ask_validates_top_k(client, farmer, top_k):
    response = client.post(
        "/api/v1/knowledge/ask",
        headers=farmer.headers,
        json={"question": "onion nitrogen", "top_k": top_k},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


def test_anonymous_ask_works_but_never_receives_farm_context(client, farmer, db):
    """The knowledge base is public; personal context is not.

    `/knowledge/ask` deliberately accepts anonymous callers (OptionalUser) — a
    visitor may ask a general question. What must never happen is farm or profile
    context leaking into an anonymous answer, because none exists for them.
    """
    response = client.post("/api/v1/knowledge/ask", json={"question": "onion nitrogen", "top_k": 3})
    assert response.status_code == 200, response.text
    anonymous = response.json()
    assert "Your crop" not in anonymous["answer"]
    assert "Your profile" not in anonymous["answer"]
    assert "farmer_farm_context" not in anonymous["source_types"]

    # The same question as a signed-in farmer may use farm context, and when it
    # does the response must declare that in `source_types`.
    mine = client.post(
        "/api/v1/knowledge/ask",
        headers=farmer.headers,
        json={"question": "onion nitrogen", "top_k": 3},
    )
    assert mine.status_code == 200, mine.text
    if "Your crop" in mine.json()["answer"]:
        assert "farmer_farm_context" in mine.json()["source_types"]
