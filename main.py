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
)

import os
from fastapi import FastAPI, Depends, HTTPException, Request, Form
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

class LogAction(BaseModel):
    log_id: int

class KBUpdate(BaseModel):
    content: str

# ---------- User API ----------
@app.post("/ask")
def ask_question(question: Question):
    answer, sources = rag_answer(question.query)
    return {"answer": answer, "sources": sources}

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
