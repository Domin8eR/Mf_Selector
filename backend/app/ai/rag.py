"""RAG pipeline — document chunk retrieval via JSONB cosine similarity.

pgvector is NOT installed. Embeddings are stored as JSONB arrays.
Cosine similarity is computed in Python after fetching all embeddings for
the relevant document scope.
"""

from __future__ import annotations

import json
import math
from typing import Any

from sqlalchemy.orm import Session


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def embed_query(text: str) -> list[float] | None:
    """Return an embedding vector for `text` using OpenAI text-embedding-3-small."""
    from app.core.config import settings
    if not settings.openai_api_key:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=settings.openai_api_key)
        resp = client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return resp.data[0].embedding
    except Exception:
        return None


def search_documents(
    query: str,
    db: Session,
    scheme_id: int | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Return the top_k most relevant document chunks for `query`.

    Scope: if scheme_id is given, only chunks from that fund's documents are
    searched. Otherwise all embedded chunks are searched.
    The function is safe to call even if no embeddings exist — it returns [].
    """
    from sqlalchemy import text

    query_vec = embed_query(query)
    if query_vec is None:
        return _keyword_fallback(query, db, scheme_id, top_k)

    # Fetch candidate (chunk_id, embedding, chunk_text, scheme_id, doc_type, as_of_date)
    if scheme_id is not None:
        rows = db.execute(
            text(
                "SELECT de.chunk_id, de.embedding, dc.chunk_text, "
                "       d.scheme_id, d.doc_type, d.as_of_date "
                "FROM selfmade_document_embedding de "
                "JOIN selfmade_document_chunk dc ON dc.id = de.chunk_id "
                "JOIN selfmade_document d ON d.id = dc.document_id "
                "WHERE d.scheme_id = :sid"
            ),
            {"sid": scheme_id},
        ).fetchall()
    else:
        rows = db.execute(
            text(
                "SELECT de.chunk_id, de.embedding, dc.chunk_text, "
                "       d.scheme_id, d.doc_type, d.as_of_date "
                "FROM selfmade_document_embedding de "
                "JOIN selfmade_document_chunk dc ON dc.id = de.chunk_id "
                "JOIN selfmade_document d ON d.id = dc.document_id "
                "LIMIT 2000"
            ),
        ).fetchall()

    if not rows:
        return []

    scored: list[tuple[float, dict]] = []
    for chunk_id, emb_json, chunk_text, s_id, doc_type, as_of_date in rows:
        if emb_json is None:
            continue
        vec = emb_json if isinstance(emb_json, list) else json.loads(emb_json)
        score = _cosine(query_vec, vec)
        scored.append((score, {
            "chunk_id": chunk_id,
            "scheme_id": s_id,
            "doc_type": doc_type,
            "as_of_date": str(as_of_date) if as_of_date else None,
            "chunk_text": chunk_text,
            "similarity": round(score, 4),
        }))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def _keyword_fallback(
    query: str,
    db: Session,
    scheme_id: int | None,
    top_k: int,
) -> list[dict]:
    """Simple ILIKE search when embeddings are unavailable."""
    from sqlalchemy import text

    words = [w.strip() for w in query.split() if len(w.strip()) > 3]
    if not words:
        return []

    like_clause = " OR ".join(f"dc.chunk_text ILIKE :w{i}" for i in range(len(words)))
    params: dict = {f"w{i}": f"%{w}%" for i, w in enumerate(words)}

    scope = "AND d.scheme_id = :sid" if scheme_id else ""
    if scheme_id:
        params["sid"] = scheme_id

    rows = db.execute(
        text(
            f"SELECT dc.id, dc.chunk_text, d.scheme_id, d.doc_type, d.as_of_date "
            f"FROM selfmade_document_chunk dc "
            f"JOIN selfmade_document d ON d.id = dc.document_id "
            f"WHERE ({like_clause}) {scope} "
            f"LIMIT :k"
        ),
        {**params, "k": top_k},
    ).fetchall()

    return [
        {
            "chunk_id": r[0],
            "scheme_id": r[2],
            "doc_type": r[3],
            "as_of_date": str(r[4]) if r[4] else None,
            "chunk_text": r[1],
            "similarity": None,
        }
        for r in rows
    ]
