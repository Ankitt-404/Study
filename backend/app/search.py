import re

from app.db import get_conn
from app.ingestion import OWNER, get_model

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
CANDIDATES = 20  # results taken from each search before merging
RRF_K = 60       # standard Reciprocal Rank Fusion constant

# Only ready documents of this owner, optionally narrowed to chosen document ids.
SCOPE = (
    "JOIN documents d ON d.id = c.document_id "
    "WHERE d.owner_id = %(owner)s AND d.status = 'ready' "
    "AND (%(ids)s::int[] IS NULL OR c.document_id = ANY(%(ids)s))"
)


def vector_search(conn, query, ids):
    vec = get_model().encode(QUERY_PREFIX + query, normalize_embeddings=True)
    rows = conn.execute(
        f"SELECT c.id FROM chunks c {SCOPE} ORDER BY c.embedding <=> %(vec)s LIMIT %(n)s",
        {"owner": OWNER, "ids": ids, "vec": vec, "n": CANDIDATES},
    ).fetchall()
    return [r[0] for r in rows]


def keyword_search(conn, query, ids):
    words = re.findall(r"[A-Za-z0-9]+", query)
    if not words:
        return []
    tsq = " | ".join(words)  # OR the words; a question never contains all of them
    rows = conn.execute(
        f"SELECT c.id FROM chunks c {SCOPE} "
        "AND c.content_tsv @@ to_tsquery('english', %(q)s) "
        "ORDER BY ts_rank_cd(c.content_tsv, to_tsquery('english', %(q)s)) DESC LIMIT %(n)s",
        {"owner": OWNER, "ids": ids, "q": tsq, "n": CANDIDATES},
    ).fetchall()
    return [r[0] for r in rows]


def fuse(vector_ids, keyword_ids):
    """Reciprocal Rank Fusion: each list adds 1/(K + rank) to a chunk's score."""
    scores = {}
    for ranking in (vector_ids, keyword_ids):
        for rank, cid in enumerate(ranking, 1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    return scores


def search(query, ids=None, k=6):
    with get_conn() as conn:
        v_ids = vector_search(conn, query, ids)
        k_ids = keyword_search(conn, query, ids)
        scores = fuse(v_ids, k_ids)
        top = sorted(scores, key=scores.get, reverse=True)[:k]
        if not top:
            return []
        rows = conn.execute(
            "SELECT c.id, d.id, d.title, c.page_start, c.page_end, c.content "
            "FROM chunks c JOIN documents d ON d.id = c.document_id "
            "WHERE c.id = ANY(%s)",
            (top,),
        ).fetchall()
    by_id = {r[0]: r for r in rows}
    results = []
    for cid in top:
        _, doc_id, title, p1, p2, content = by_id[cid]
        results.append({
            "chunk_id": cid,
            "document_id": doc_id,
            "title": title,
            "pages": f"{p1}-{p2}" if p1 != p2 else str(p1),
            "score": round(scores[cid], 4),
            "found_by": [n for n, lst in (("vector", v_ids), ("keyword", k_ids)) if cid in lst],
            "content": content,
        })
    return results