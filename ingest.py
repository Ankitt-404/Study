import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()

SEMESTER = 3
FILE = Path(__file__).parent / "data" / "semester3_syllabus_clean.md"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
MAX_CHARS = 1400
OVERVIEW_SECTIONS = ("Learning Objectives", "Prerequisite", "Module Table")


def split_by_heading(text, marker):
    """Split at lines starting with marker. Returns (text before first heading, [(heading, body)])."""
    preamble, parts = [], []
    for line in text.splitlines():
        if line.startswith(marker):
            parts.append([line[len(marker):].strip(), []])
        elif parts:
            parts[-1][1].append(line)
        else:
            preamble.append(line)
    return "\n".join(preamble).strip(), [(h, "\n".join(b).strip()) for h, b in parts]


def split_long(text, limit=MAX_CHARS):
    """Break long text at line boundaries so each part stays under the limit."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for line in text.splitlines():
        if current and len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        parts.append(current)
    return [p.strip() for p in parts]


def build_chunks(name, code, preamble, sections):
    label = f"Semester {SEMESTER} | {name}" + (f" ({code})" if code else "")
    overview = [preamble] + [f"{h}:\n{b}" for h, b in sections if h.startswith(OVERVIEW_SECTIONS)]
    chunks = [("Overview", None, "\n\n".join(x for x in overview if x))]
    books = []

    for h, b in sections:
        if h.startswith(OVERVIEW_SECTIONS):
            continue
        if h.startswith("Module"):
            chunks.append(("Module", h, f"{h}\n{b}"))
        elif h.startswith("Course Outcomes"):
            chunks.append(("Course outcomes", None, b))
        elif h.endswith("Books"):
            books.append(f"{h}:\n{b}")
        elif h.startswith("List of Practicals"):
            chunks.append(("Practicals", None, b))
        else:
            print(f"  Unknown section ignored: {h}")
    if books:
        chunks.append(("Books", None, "\n\n".join(books)))

    out = []
    for section, module, body in chunks:
        topic = module or section
        parts = split_long(body)
        for i, part in enumerate(parts, 1):
            suffix = f" (part {i} of {len(parts)})" if len(parts) > 1 else ""
            out.append((section, module, f"{label} | {topic}{suffix}\n{part}"))
    return out


def main():
    text = FILE.read_text(encoding="utf-8")
    lines = [
        l for l in text.splitlines()
        if l.strip() != "---" and not re.match(r"^\|[-| ]+\|$", l.strip())
    ]
    _, blocks = split_by_heading("\n".join(lines), "## ")

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        register_vector(conn)
        subjects = {
            name: (sid, code)
            for sid, name, code in conn.execute(
                "SELECT id, name, code FROM subjects WHERE semester = %s", (SEMESTER,)
            ).fetchall()
        }

        rows = []  # (subject_id, section, module, pages, content)
        for title, body in blocks:
            if title not in subjects:
                print(f"Skipping section (not a subject): {title}")
                continue
            subject_id, code = subjects[title]
            preamble, sections = split_by_heading(body, "### ")
            m = re.search(r"Pages?\s+(\d+(?:-\d+)?)", preamble)
            pages = m.group(1) if m else None
            for section, module, content in build_chunks(title, code, preamble, sections):
                rows.append((subject_id, section, module, pages, content))

        missing = set(subjects) - {t for t, _ in blocks}
        if missing:
            print(f"WARNING: subjects with no section in the file: {sorted(missing)}")

        print(f"Built {len(rows)} chunks. Embedding...")
        model = SentenceTransformer(MODEL_NAME)
        vectors = model.encode(
            [r[4] for r in rows], normalize_embeddings=True, batch_size=32, show_progress_bar=True
        )

        # Only delete old chunks after embedding succeeded.
        conn.execute("DELETE FROM chunks WHERE semester = %s", (SEMESTER,))
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks (subject_id, semester, section, module, pages, content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [(r[0], SEMESTER, r[1], r[2], r[3], r[4], v) for r, v in zip(rows, vectors)],
            )
    print(f"Stored {len(rows)} chunks for semester {SEMESTER}.")


if __name__ == "__main__":
    main()