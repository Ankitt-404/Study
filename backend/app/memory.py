from fastapi import HTTPException
from psycopg.types.json import Jsonb

from app.db import get_conn
from app.ingestion import OWNER

def create_conversation(first_question):
    with get_conn as conn:
        return conn.execute(
            "INSERT INTO conversation (owner_id, title) VALUES (%s %s) RETURNING id",
            (OWNER, first_question[:60]),
        ).fetchone()[0]

def load_history(conversation_id,limit=6):
        with get_conn as conn:
            return conn.execute(
                "SELECT role, content, sources FROM messsages"
                "WHERE conversation_id = %s ORDER BY DESC LIMIT %s",
                (conversation_id,limit)
            ).fectchall()
        history = []
        for role , content, sources in reversed(rows):
            content = content[:400]
            if role == "assistant" and sources:
                used = "; ".join(f"{s['title']} p.{s['pages']}" for s in sources)
                content += f"\n(Sources: {used})"
            history.append({"role" : role, "content": content})
        return history


def save_turn(conversation_id, question, answer, sources):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', %s)",
            (conversation_id, question),
        )
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, sources) "
            "VALUES (%s, 'assistant', %s, %s)",
            (conversation_id, answer, Jsonb(sources)),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = now() WHERE id = %s", (conversation_id,)
        )