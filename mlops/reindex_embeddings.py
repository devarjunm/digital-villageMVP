#!/usr/bin/env python
"""Re-embed the corpus (knowledge chunks and community posts) after a provider change.

Why this exists: vectors are only comparable inside the embedding space that
produced them. Switching `EMBEDDING_PROVIDER` (or its model/dimension) invalidates
every stored vector, and semantic search will silently return nonsense unless the
corpus is re-embedded. `docs/deployment.md` §6 requires this step; this is the tool
it refers to.

    python mlops/reindex_embeddings.py --dry-run          # what would be re-embedded
    python mlops/reindex_embeddings.py                    # enqueue the job(s) for the worker
    python mlops/reindex_embeddings.py --inline           # run now, in this process
    python mlops/reindex_embeddings.py --scope posts

The work itself is the registered `embedding_reindex` worker job, so provenance,
retries and progress reporting behave exactly as they do in production. This script
only decides *whether* it is safe to run, and warns loudly about the consequences.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT))

SCOPES = ("posts", "documents", "all")


def _counts() -> dict[str, int]:
    import sqlalchemy as sa

    from app.community.models import Post
    from app.core.enums import ContentStatus
    from app.database.session import session_scope
    from app.knowledge.models import KnowledgeChunk, KnowledgeDocument

    with session_scope() as db:
        posts = db.execute(
            sa.select(sa.func.count())
            .select_from(Post)
            .where(Post.deleted_at.is_(None), Post.status == ContentStatus.PUBLISHED)
        ).scalar_one()
        documents = db.execute(
            sa.select(sa.func.count())
            .select_from(KnowledgeDocument)
            .where(KnowledgeDocument.deleted_at.is_(None))
        ).scalar_one()
        chunks = db.execute(
            sa.select(sa.func.count()).select_from(KnowledgeChunk)
        ).scalar_one()
    return {"posts": int(posts), "documents": int(documents), "chunks": int(chunks)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--scope", choices=SCOPES, default="all", help="what to re-embed"
    )
    parser.add_argument(
        "--batch-size", type=int, default=25, help="rows per job invocation"
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="run the job in this process instead of queueing it",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report and exit without changing anything",
    )
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )
    args = parser.parse_args(argv)

    if not os.environ.get("DATABASE_URL"):
        print(
            "DATABASE_URL is not set; see docs/development.md §3 for the development value."
        )
        return 2

    from app.core.config import settings

    counts = _counts()
    provider = settings.embedding_provider
    dimension = settings.embedding_dim

    print("Embedding configuration in use")
    print(f"  provider : {provider}")
    print(f"  model    : {settings.embedding_model}")
    print(f"  dimension: {dimension}")
    print(f"  version  : {settings.embedding_version}")
    if provider == "mock":
        print(
            "  NOTE: this is the demo embedding provider — vectors are lexical hashes. Re-embedding is\n"
            "        still consistent, but semantic quality will be limited until a real model is configured."
        )

    print("\nCorpus to re-embed")
    print(f"  published posts : {counts['posts']}")
    print(
        f"  documents       : {counts['documents']} ({counts['chunks']} stored chunks)"
    )

    if args.dry_run:
        print("\nDry run: nothing was re-embedded.")
        print(
            "Remember to update EMBEDDING_VERSION (and EMBEDDING_DIM if it changed) so a future deploy can\n"
            "tell which vectors belong to which model."
        )
        return 0

    if not args.yes:
        print(
            "\nRe-embedding overwrites stored vectors for the selected scope. Search results are degraded\n"
            "until it finishes (no results rather than wrong results, because the query vector space must\n"
            "match the stored one). Continue? [y/N] ",
            end="",
        )
        answer = input().strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted; nothing was changed.")
            return 1

    from app.core.enums import JobKind
    from app.workers.queue import JobQueue

    queue = JobQueue()
    scope = (
        "posts"
        if args.scope == "posts"
        else ("documents" if args.scope == "documents" else "all")
    )
    result = queue.enqueue(
        kind=JobKind.EMBEDDING_REINDEX,
        payload={
            "scope": scope,
            "batch_size": args.batch_size,
            "reason": f"operator re-embed via mlops/reindex_embeddings.py (provider={provider})",
        },
        run_inline=args.inline,
    )
    print(
        f"\nJob {result.job_id} — status: {result.status} (queue mode: {result.mode})"
    )
    if result.status == "succeeded":
        print("Result:", result.result)
    else:
        print(
            "The worker will pick this up; watch it with: python -m app.workers.main --status"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
