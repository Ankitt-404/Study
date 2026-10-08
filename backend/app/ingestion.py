import hashlib
import re
from collections import Counter

import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer

from app.db import get_conn

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MAX_TOKENS = 300       # chunk size target (model limit is 512)
OVERLAP_TOKENS = 50
OWNER = "local"        # placeholder until login exists

_model = None


def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def norm(line):
    return re.sub(r"\d+", "#", line)  # "Page. 73" and "Page. 74" compare equal


def extract_pages(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [
        (i + 1, [l.strip() for l in page.get_text().splitlines() if l.strip()])
        for i, page in enumerate(doc)
    ]
    chars = sum(len(l) for _, lines in pages for l in lines)
    if chars < 30 * max(len(pages), 1):
        raise ValueError("No extractable text. Scanned PDFs need OCR.")
    return pages


def strip_headers_footers(pages):
    """Drop lines at the top/bottom edge that repeat on most pages."""
    if len(pages) < 4:
        return pages
    counts = Counter()
    for _, lines in pages:
        counts.update({norm(l) for l in lines[:3] + lines[-3:]})
    common = {k for k, c in counts.items() if c >= 0.6 * len(pages)}
    out = []
    for n, lines in pages:
        last = len(lines) - 3
        out.append((n, [
            l for i, l in enumerate(lines)
            if not ((i < 3 or i >= last) and norm(l) in common)
        ]))
    return out


def make_units(pages, tokenizer):
    """One unit per line (very long lines are split), with its page and token count."""
    units = []
    for page, lines in pages:
        for line in lines:
            words = line.split()
            pieces = [line] if len(words) <= 150 else [
                " ".join(words[i:i + 150]) for i in range(0, len(words), 150)
            ]
            units.extend((p, page) for p in pieces)
    ids = tokenizer([u[0] for u in units], add_special_tokens=False)["input_ids"]
    return [(text, page, len(i)) for (text, page), i in zip(units, ids)]


def chunk_units(units):
    """Pack units into ~MAX_TOKENS chunks, carrying ~OVERLAP_TOKENS into the next one."""
    chunks, cur, cur_tok = [], [], 0
    for unit in units:
        if cur and cur_tok + unit[2] > MAX_TOKENS:
            chunks.append(cur)
            overlap, t = [], 0
            for u in reversed(cur):
                if t + u[2] > OVERLAP_TOKENS:
                    break
                overlap.insert(0, u)
                t += u[2]
            cur, cur_tok = overlap, t
        cur.append(unit)
        cur_tok += unit[2]
    if cur:
        chunks.append(cur)
    return [("\n".join(u[0] for u in c), c[0][1], c[-1][1]) for c in chunks]


def create_document(filename, pdf_bytes):
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    title = re.sub(r"\.pdf$", "", filename, flags=re.I)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, status FROM documents WHERE owner_id = %s AND sha256 = %s",
            (OWNER, sha),
        ).fetchone()
        if row and row[1] != "failed":
            return row[0], row[1], False
        if row:  # retry a failed upload
            conn.execute("DELETE FROM documents WHERE id = %s", (row[0],))
        doc_id = conn.execute(
            "INSERT INTO documents (owner_id, title, filename, sha256) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (OWNER, title, filename, sha),
        ).fetchone()[0]
    return doc_id, "queued", True


def process_document(doc_id, pdf_bytes):
    try:
        with get_conn() as conn:
            conn.execute("UPDATE documents SET status = 'processing' WHERE id = %s", (doc_id,))
            title = conn.execute("SELECT title FROM documents WHERE id = %s", (doc_id,)).fetchone()[0]

        pages = strip_headers_footers(extract_pages(pdf_bytes))
        model = get_model()
        chunks = chunk_units(make_units(pages, model.tokenizer))
        if not chunks:
            raise ValueError("No text found after cleaning.")
        # The title is embedded with each chunk for context, but stored content stays raw.
        vectors = model.encode(
            [f"{title}\n{c[0]}" for c in chunks], normalize_embeddings=True, batch_size=32
        )

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO chunks (document_id, chunk_index, page_start, page_end, "
                    "content, embedding, embedding_model) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [(doc_id, i, c[1], c[2], c[0], v, MODEL_NAME)
                     for i, (c, v) in enumerate(zip(chunks, vectors))],
                )
            conn.execute(
                "UPDATE documents SET status = 'ready', page_count = %s WHERE id = %s",
                (len(pages), doc_id),
            )
    except Exception as e:
        with get_conn() as conn:
            conn.execute(
                "UPDATE documents SET status = 'failed', error = %s WHERE id = %s",
                (str(e)[:500], doc_id),
            )