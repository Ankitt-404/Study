from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from pydantic import BaseModel, Field
from app.answer import answer_question
from app.search import search
from app.db import get_conn
from app.ingestion import create_document, process_document
from app.memory import create_conversation, load_history, save_turn
MAX_BYTES = 25 * 1024 * 1024

app = FastAPI()


@app.get("/")
def home():
    return {"status": "ok"}


@app.post("/documents", status_code=202)
def upload(file: UploadFile, background: BackgroundTasks):
    data = file.file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 25 MB).")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Not a PDF file.")
    doc_id, status, is_new = create_document(file.filename or "upload.pdf", data)
    if is_new:
        background.add_task(process_document, doc_id, data)
    return {"id": doc_id, "status": status}


@app.get("/documents")
def list_documents():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, status, page_count FROM documents ORDER BY id DESC"
        ).fetchall()
    return [{"id": r[0], "title": r[1], "status": r[2], "pages": r[3]} for r in rows]


@app.get("/documents/{doc_id}")
def get_document(doc_id: int):
    with get_conn() as conn:
        r = conn.execute(
            "SELECT d.id, d.title, d.status, d.error, d.page_count, "
            "(SELECT COUNT(*) FROM chunks WHERE document_id = d.id) "
            "FROM documents d WHERE d.id = %s",
            (doc_id,),
        ).fetchone()
    if not r:
        raise HTTPException(404, "Document not found.")
    return {"id": r[0], "title": r[1], "status": r[2], "error": r[3], "pages": r[4], "chunks": r[5]}


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    document_ids: list[int] | None = None
    k: int = Field(default=6, ge=1, le=20)


@app.post("/search")
def search_endpoint(body: SearchRequest):
    return search(body.query, body.document_ids, body.k)

class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    document_ids: list[int] | None = None
    k: int = Field(default=3, ge=1, le=10)
    conversation_id: int | None = None


@app.post("/chat")
def chat(body: ChatRequest):
    if body.conversation_id is None:
        cid = create_conversation(body.question)
        history = []
    else:
        cid = body.conversation_id
        history = load_history(cid)
    result = answer_question(body.question, body.document_ids, body.k, history)
    save_turn(cid, body.question, result["answer"], result["sources"])
    return {"conversation_id": cid, **result}