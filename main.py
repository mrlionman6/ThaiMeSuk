from db import (
    init_db,
    get_all_knowledge_base_with_ids,
    get_all_knowledge_base_full,
    add_knowledge_chunk,
    update_knowledge_chunk,
    delete_knowledge_chunk,
    get_chunks_missing_embeddings,
    set_embedding,
    get_vector_scores_for_all,
    get_logs,
    get_logs_paginated,
    log_low_confidence_query,
    approve_log as db_approve_log,   # alias กัน shadow ชื่อกับ endpoint ด้านล่าง
    reject_log as db_reject_log,     # alias กัน shadow ชื่อกับ endpoint ด้านล่าง
    create_user,
    get_user_by_email,
    get_user_by_id,
    create_chat_session,
    touch_chat_session,
    get_user_chats,
    get_chat_session,
    add_chat_message,
    get_chat_messages,
    delete_chat_session,
)

import os
import json
import bcrypt
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
import anthropic
from sentence_transformers import SentenceTransformer, CrossEncoder
from rank_bm25 import BM25Okapi
from pythainlp.tokenize import word_tokenize
import numpy as np
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "change-this-secret-key"))

# ---------- โหลดโมเดล ----------
print("กำลังโหลดโมเดล...")
embed_model = SentenceTransformer('intfloat/multilingual-e5-large')
reranker = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')
print("โหลดโมเดลสำเร็จ")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")

def require_login(request: Request):
    if not request.session.get("logged_in"):
        raise HTTPException(status_code=401, detail="Not logged in")
    return True

# ---------- User auth (แยกจาก admin โดยสิ้นเชิง — คนละ session key, คนละระบบ) ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

def require_user(request: Request) -> int:
    """dependency สำหรับ endpoint ที่ต้อง login เป็น user (ไม่ใช่ admin) — คืนค่า user_id"""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user_id

# ---------- Knowledge Base ----------
# ไม่โหลดจากไฟล์ JSON ตอน import แล้ว — ข้อมูลจะถูกโหลดจาก DB ตอน startup event (ด้านล่าง)
knowledge_base_ids = []     # list ของ id เรียงตาม index เดียวกับ knowledge_base_texts (ใช้จับคู่กับผลลัพธ์ vector score จาก DB)
knowledge_base_texts = []   # list ของ content เรียงลำดับเดียวกับ knowledge_base_ids — ใช้เป็น corpus ของ BM25

def build_index():
    global bm25
    tokenized_kb = [word_tokenize(doc, engine="newmm") for doc in knowledge_base_texts]
    bm25 = BM25Okapi(tokenized_kb)
    # หมายเหตุ: ไม่มี kb_embeddings ใน memory อีกต่อไป — vector score คำนวณผ่าน pgvector โดยตรงตอนค้นหา (ดู hybrid_search)

def backfill_missing_embeddings():
    """เติม embedding ให้ chunk ที่ยังไม่มีค่า (เช่น chunk เก่าก่อนเพิ่มฟีเจอร์ pgvector, หรือ insert แบบไม่ผ่าน endpoint)
    เรียกทุกครั้งตอน rebuild_index() — ถ้าไม่มี chunk ขาดเลยจะไม่ทำอะไร (loop ว่าง)"""
    missing = get_chunks_missing_embeddings()
    for chunk in missing:
        embedding = embed_model.encode(chunk["content"]).tolist()
        set_embedding(chunk["id"], embedding)
    if missing:
        print(f"Backfill embedding ให้ {len(missing)} chunk ที่ยังไม่มีค่า")

def rebuild_index():
    global knowledge_base_ids, knowledge_base_texts
    backfill_missing_embeddings()  # เติม embedding ที่ขาดก่อน จะได้ครบทุก chunk ตอนค้นหา
    rows = get_all_knowledge_base_with_ids()   # ดึงจาก PostgreSQL แทน json.load
    knowledge_base_ids = [r["id"] for r in rows]
    knowledge_base_texts = [r["content"] for r in rows]
    build_index()

# ---------- RAG Pipeline ----------
def hybrid_search(query, k=5, alpha=0.5):
    # ฝั่ง keyword: BM25 คำนวณใน memory เหมือนเดิม (ไม่มี native full-text index ที่เหมาะสมใน Postgres สำหรับเคสนี้)
    tokenized_query = word_tokenize(query, engine="newmm")
    bm25_scores = np.array(bm25.get_scores(tokenized_query))

    # ฝั่ง semantic: ให้ pgvector คำนวณ cosine distance ให้ทั้งหมดผ่าน SQL โดยตรง (ไม่ใช่ python/numpy loop)
    query_embedding = embed_model.encode(query).tolist()
    vector_scores_map = get_vector_scores_for_all(query_embedding)  # {id: similarity} จาก DB
    vector_scores = np.array([vector_scores_map.get(cid, 0.0) for cid in knowledge_base_ids])

    def normalize(scores):
        if scores.max() == scores.min():
            return np.zeros_like(scores)
        return (scores - scores.min()) / (scores.max() - scores.min())

    final_scores = alpha * normalize(vector_scores) + (1 - alpha) * normalize(bm25_scores)
    top_idx = final_scores.argsort()[::-1][:k]
    return [knowledge_base_texts[i] for i in top_idx]

def rerank_with_scores(query, candidates, top_k=3):
    pairs = [[query, c] for c in candidates]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    top_texts = [text for text, score in ranked[:top_k]]
    top_scores = [float(score) for text, score in ranked[:top_k]]
    return top_texts, top_scores

DISCLAIMER = (
    "\n\n⚠️ ข้อมูลนี้เป็นความรู้เบื้องต้นเท่านั้น ไม่ใช่คำแนะนำทางกฎหมาย "
    "กรุณาปรึกษาทนายความหรือหน่วยงานราชการที่เกี่ยวข้องสำหรับกรณีเฉพาะของท่าน"
)

def rag_answer(query):
    candidates = hybrid_search(query, k=5)
    top_chunks, scores = rerank_with_scores(query, candidates, top_k=3)
    context = "\n".join([f"- {c}" for c in top_chunks])

    prompt = "คุณเป็นผู้ช่วยให้ความรู้กฎหมายเบื้องต้นแก่ประชาชนไทย\n\n"
    prompt += "ข้อมูลอ้างอิงที่อาจเกี่ยวข้อง (ใช้ประกอบถ้าตรงกับคำถาม):\n" + context + "\n\n"
    prompt += "คำถาม: " + query + "\n\n"
    prompt += "คำแนะนำในการตอบ:\n"
    prompt += "- ถ้าข้อมูลอ้างอิงข้างต้นตรงกับคำถาม ให้ใช้ข้อมูลนั้นเป็นหลัก\n"
    prompt += "- ถ้าข้อมูลอ้างอิงไม่ครอบคลุมหรือไม่มีรายละเอียดพอ ให้ใช้ความรู้ทั่วไปของคุณตอบเสริมให้ครบถ้วนที่สุด โดยไม่ต้องบอกผู้ใช้ว่าข้อมูลอ้างอิงไม่พอ\n"
    prompt += "- ตอบให้มั่นใจ ชัดเจน เป็นประโยชน์ที่สุดสำหรับผู้ถาม\n"
    prompt += "- ห้ามใส่ข้อความ disclaimer หรือคำเตือนใดๆ ท้ายคำตอบเอง ระบบจะเป็นผู้เพิ่มให้เองภายหลัง\n\n"
    prompt += "ตอบเป็นภาษาไทย กระชับ เข้าใจง่ายสำหรับประชาชนทั่วไป"

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )
    answer = response.content[0].text.strip() + DISCLAIMER  # บังคับเพิ่มด้วยโค้ด ไม่พึ่ง LLM ทำตาม prompt เพียงอย่างเดียว

    CONFIDENCE_THRESHOLD = 0.3
    if len(scores) == 0 or max(scores) < CONFIDENCE_THRESHOLD:
        log_low_confidence_query(query, answer, top_chunks, max(scores) if scores else 0)

    return answer, top_chunks

# ---------- Pydantic Models (ต้องประกาศก่อนใช้งานด้านล่าง) ----------
class Question(BaseModel):
    query: str
    chat_id: Optional[int] = None

class LogAction(BaseModel):
    log_id: int

class KBUpdate(BaseModel):
    content: str

class KBCreate(BaseModel):
    content: str

class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class ChatCreateRequest(BaseModel):
    title: Optional[str] = None

# ---------- User API ----------
@app.post("/ask")
def ask_question(question: Question, request: Request):
    answer, sources = rag_answer(question.query)

    user_id = request.session.get("user_id")
    chat_id = question.chat_id

    if user_id:
        if chat_id is None:
            # ยังไม่มีแชทอยู่ (ผู้ใช้เพิ่งเริ่มถามคำถามแรก) — สร้างแชทใหม่ ตั้งชื่อจากคำถามแรก
            title = question.query.strip()[:50] or "แชทใหม่"
            chat_id = create_chat_session(user_id, title=title)
        else:
            # เช็คว่าแชทนี้เป็นของ user คนนี้จริง กัน user คนอื่นยัดข้อความใส่แชทของคนอื่น
            if get_chat_session(chat_id, user_id) is None:
                raise HTTPException(status_code=404, detail="ไม่พบแชทนี้")

        add_chat_message(chat_id, "user", question.query)
        add_chat_message(chat_id, "assistant", answer)
        touch_chat_session(chat_id)

    return {"answer": answer, "sources": sources, "chat_id": chat_id}

# ---------- Auth API (สำหรับผู้ใช้ทั่วไป — แยกจาก admin) ----------
@app.post("/api/auth/register")
def register(body: RegisterRequest, request: Request):
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="อีเมลไม่ถูกต้อง")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร")

    password_hash = hash_password(body.password)
    new_id = create_user(email, password_hash)
    if new_id is None:
        raise HTTPException(status_code=409, detail="อีเมลนี้มีผู้ใช้งานแล้ว")

    request.session["user_id"] = new_id
    return {"status": "registered", "user": {"id": new_id, "email": email}}

@app.post("/api/auth/login")
def user_login(body: LoginRequest, request: Request):
    email = body.email.strip().lower()
    user = get_user_by_email(email)
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง")

    request.session["user_id"] = user["id"]
    return {"status": "logged_in", "user": {"id": user["id"], "email": user["email"]}}

@app.post("/api/auth/logout")
def user_logout(request: Request):
    request.session.pop("user_id", None)
    return {"status": "logged_out"}

@app.get("/api/auth/me")
def auth_me(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return {"logged_in": False}
    user = get_user_by_id(user_id)
    if user is None:
        request.session.pop("user_id", None)  # user ถูกลบไปแล้วแต่ session ยังค้าง — ล้างทิ้ง
        return {"logged_in": False}
    return {"logged_in": True, "user": user}

# ---------- Chat API (ต้อง login เป็น user ก่อนทุก endpoint) ----------
@app.get("/api/chats")
def list_chats(user_id: int = Depends(require_user)):
    return {"chats": get_user_chats(user_id)}

@app.post("/api/chats")
def create_chat(body: ChatCreateRequest, user_id: int = Depends(require_user)):
    title = (body.title or "แชทใหม่").strip()[:100]
    new_id = create_chat_session(user_id, title=title)
    return {"status": "created", "id": new_id}

@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: int, user_id: int = Depends(require_user)):
    chat = get_chat_session(chat_id, user_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="ไม่พบแชทนี้")
    messages = get_chat_messages(chat_id)
    return {"chat": chat, "messages": messages}

@app.delete("/api/chats/{chat_id}")
def remove_chat(chat_id: int, user_id: int = Depends(require_user)):
    ok = delete_chat_session(chat_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="ไม่พบแชทนี้")
    return {"status": "deleted"}

# ---------- Startup Event ----------
@app.on_event("startup")
async def startup_event():
    init_db()       # สร้างตาราง knowledge_base และ logs ถ้ายังไม่มี
    rebuild_index()  # โหลด knowledge base จาก DB + build BM25/vector index

# ---------- Admin Login/Logout ----------
@app.get("/admin/login")
def login_page():
    return FileResponse("static/login.html")

@app.post("/admin/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session["logged_in"] = True
        return RedirectResponse(url="/admin", status_code=303)
    return RedirectResponse(url="/admin/login?error=1", status_code=303)

@app.get("/admin/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)

# ---------- Admin Page & API (คำถามรอตรวจสอบ) ----------
@app.get("/admin")
def admin_page(request: Request):
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/admin/login")
    return FileResponse("static/admin.html")

@app.get("/admin/api/logs")
def get_pending_logs(page: int = 1, page_size: int = 10, _: bool = Depends(require_login)):
    result = get_logs_paginated(status="pending", page=page, page_size=page_size)
    return {"logs": result["items"], "total": result["total"], "page": page, "page_size": page_size}

@app.post("/admin/api/approve")
def approve_log(action: LogAction, _: bool = Depends(require_login)):
    # หา log ที่ตรงกับ id เพื่อเอา query/answer มาต่อเป็น chunk ใหม่
    matching = [l for l in get_logs() if l["id"] == action.log_id]
    if not matching:
        raise HTTPException(status_code=404, detail="Log not found")
    log = matching[0]

    new_chunk = f"{log['query']} — {log['answer']}"
    embedding = embed_model.encode(new_chunk).tolist()
    add_knowledge_chunk(new_chunk, embedding=embedding)
    db_approve_log(action.log_id)
    rebuild_index()

    return {"status": "approved"}

@app.post("/admin/api/reject")
def reject_log(action: LogAction, _: bool = Depends(require_login)):
    db_reject_log(action.log_id)
    return {"status": "rejected"}

# ---------- Admin API (จัดการ Knowledge Base โดยตรง — แท็บใหม่) ----------
@app.get("/admin/api/kb")
def list_kb(page: int = 1, page_size: int = 10, _: bool = Depends(require_login)):
    result = get_all_knowledge_base_full(page=page, page_size=page_size)
    return {"chunks": result["items"], "total": result["total"], "page": page, "page_size": page_size}

@app.post("/admin/api/kb")
def create_kb(body: KBCreate, _: bool = Depends(require_login)):
    """เพิ่ม chunk เดี่ยว พิมพ์เองผ่านหน้า admin — คำนวณ embedding ทันที ไม่ต้อง restart"""
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="เนื้อหาห้ามว่างเปล่า")
    embedding = embed_model.encode(content).tolist()
    new_id = add_knowledge_chunk(content, embedding=embedding)
    rebuild_index()
    return {"status": "created", "id": new_id}

@app.post("/admin/api/kb/bulk")
async def bulk_create_kb(file: UploadFile = File(...), _: bool = Depends(require_login)):
    """Import หลาย chunk พร้อมกันจากไฟล์ — รองรับ .json (list ของ string หรือ dict ที่มี key content
    เหมือนโครงสร้าง knowledge_base.json เดิม) หรือ .txt (หนึ่งบรรทัดต่อหนึ่ง chunk)"""
    raw = await file.read()
    try:
        text_content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="อ่านไฟล์ไม่ได้ — ต้องเป็น UTF-8 text เท่านั้น")

    filename = (file.filename or "").lower()
    if filename.endswith(".json"):
        try:
            data = json.loads(text_content)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="ไฟล์ JSON รูปแบบไม่ถูกต้อง")
        items = [d["content"] if isinstance(d, dict) else str(d) for d in data]
    else:
        # .txt หรือนามสกุลอื่น: ถือว่าหนึ่งบรรทัดคือหนึ่ง chunk ข้ามบรรทัดว่าง
        items = [line.strip() for line in text_content.splitlines() if line.strip()]

    items = [i.strip() for i in items if i and i.strip()]
    if not items:
        raise HTTPException(status_code=400, detail="ไม่พบเนื้อหาที่ import ได้ในไฟล์นี้")

    embeddings = embed_model.encode(items)  # batch encode ครั้งเดียว เร็วกว่า loop เรียกทีละตัว
    added_ids = [
        add_knowledge_chunk(content, embedding=embedding.tolist())
        for content, embedding in zip(items, embeddings)
    ]

    rebuild_index()
    return {"status": "created", "count": len(added_ids), "ids": added_ids}

@app.put("/admin/api/kb/{chunk_id}")
def edit_kb(chunk_id: int, body: KBUpdate, _: bool = Depends(require_login)):
    embedding = embed_model.encode(body.content).tolist()  # เนื้อหาเปลี่ยน embedding เดิมใช้ไม่ได้แล้ว ต้องคำนวณใหม่เสมอ
    ok = update_knowledge_chunk(chunk_id, body.content, embedding=embedding)
    if not ok:
        raise HTTPException(status_code=404, detail="Chunk not found")
    rebuild_index()
    return {"status": "updated"}

@app.delete("/admin/api/kb/{chunk_id}")
def delete_kb(chunk_id: int, _: bool = Depends(require_login)):
    ok = delete_knowledge_chunk(chunk_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Chunk not found")
    rebuild_index()
    return {"status": "deleted"}


# ---------- เสิร์ฟหน้าเว็บผู้ใช้ ----------
@app.get("/")
def read_root():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
