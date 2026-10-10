import json
import logging

from app.db import get_conn
from app.ingestion import OWNER
from app.search import search

log = logging.getLogger(__name__)

MAX_PAGES = 3
MAX_CHUNK_CHARS = 1500

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": (
                "Search the user's uploaded documents and return the most relevant passages. "
                "Use specific keywords. If the results do not answer the question, call again "
                "with a different query."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Standalone search query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_pages",
            "description": (
                "Read the text on specific pages of one document. Use when a search result looks "
                "incomplete or the user names a page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "integer"},
                    "start_page": {"type": "integer"},
                    "end_page": {"type": "integer"},
                },
                "required": ["document_id", "start_page", "end_page"],
            },
        },
    },
]


class SourceRegistry:
    """Gives every chunk the model sees one stable number [1], [2]... across all tool calls."""

    def __init__(self):
        self.by_chunk = {}
        self.items = []

    def number(self, chunk):
        cid = chunk["chunk_id"]
        if cid not in self.by_chunk:
            self.items.append(chunk)
            self.by_chunk[cid] = len(self.items)
        return self.by_chunk[cid]


def format_chunks(chunks, registry):
    if not chunks:
        return "No results."
    parts = []
    for c in chunks:
        n = registry.number(c)
        parts.append(
            f"[{n}] ({c['title']}, doc {c['document_id']}, pages {c['pages']})\n"
            f"{c['content'][:MAX_CHUNK_CHARS]}"
        )
    return "\n\n".join(parts)


def read_pages(doc_id, start, end, doc_ids):
    if doc_ids and doc_id not in doc_ids:
        return None, "Error: that document is not in scope."
    if end < start or end - start + 1 > MAX_PAGES:
        return None, f"Error: request at most {MAX_PAGES} pages at a time."
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT c.id, d.id, d.title, c.page_start, c.page_end, c.content "
            "FROM chunks c JOIN documents d ON d.id = c.document_id "
            "WHERE d.owner_id = %s AND d.status = 'ready' AND d.id = %s "
            "AND c.page_start <= %s AND c.page_end >= %s "
            "ORDER BY c.chunk_index LIMIT 8",
            (OWNER, doc_id, end, start),
        ).fetchall()
    chunks = [
        {
            "chunk_id": r[0],
            "document_id": r[1],
            "title": r[2],
            "pages": f"{r[3]}-{r[4]}" if r[3] != r[4] else str(r[3]),
            "content": r[5],
        }
        for r in rows
    ]
    if not chunks:
        with get_conn() as conn:
              r = conn.execute(
                "SELECT title, page_count FROM documents WHERE id = %s AND owner_id = %s",
                (doc_id, OWNER),
            ).fetchone()
        if not r:
            return None, f"Error: document {doc_id} does not exist."
        return None, (
            f"No text found on pages {start}-{end}. Document {doc_id} ('{r[0]}') has "
            f"{r[1]} pages, numbered by position in the file."
        )
    return chunks, None


def run_tool(name, raw_args, registry, doc_ids):
    try:
        args = json.loads(raw_args or "{}")
    except json.JSONDecodeError:
        return "Error: arguments were not valid JSON."
    try:
        if name == "search_documents":
            query = str(args.get("query", "")).strip()[:500]
            if not query:
                return "Error: query is empty."
            return format_chunks(search(query, doc_ids, 3), registry)
        if name == "read_pages":
            chunks, err = read_pages(
                int(args["document_id"]), int(args["start_page"]), int(args["end_page"]), doc_ids
            )
            return err or format_chunks(chunks, registry)
    except Exception:
        log.exception("tool %s failed", name)
        return "Error: the tool failed. Try a different request."
    return f"Error: unknown tool {name}."