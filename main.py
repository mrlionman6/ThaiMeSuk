from db import (
    init_db,
    get_all_knowledge_base,
    add_knowledge_chunk,
    get_logs,
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
from sentence_transformers import SentenceTransformer, CrossEncoder, util
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
knowledge_base = []

def build_index():
    global kb_embeddings, bm25
    kb_embeddings = embed_model.encode(knowledge_base)
    tokenized_kb = [word_tokenize(doc, engine="newmm") for doc in knowledge_base]
    bm25 = BM25Okapi(tokenized_kb)

def rebuild_index():
    global knowledge_base
    knowledge_base = get_all_knowledge_base()   # ดึงจาก PostgreSQL แทน json.load
    build_index()

# ---------- RAG Pipeline ----------
def hybrid_search(query, k=5, alpha=0.5):
    query_embedding = embed_model.encode(query)
    vector_scores = util.cos_sim(query_embedding, kb_embeddings)[0].numpy()
    tokenized_query = word_tokenize(query, engine="newmm")
    bm25_scores = np.array(bm25.get_scores(tokenized_query))

    def normalize(scores):
        if scores.max() == scores.min():
            return np.zeros_like(scores)
        return (scores - scores.min()) / (scores.max() - scores.min())

    final_scores = alpha * normalize(vector_scores) + (1 - alpha) * normalize(bm25_scores)
    top_idx = final_scores.argsort()[::-1][:k]
    return [knowledge_base[i] for i in top_idx]

def rerank_with_scores(query, candidates, top_k=3):
    pairs = [[query, c] for c in candidates]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    top_texts = [text for text, score in ranked[:top_k]]
    top_scores = [float(score) for text, score in ranked[:top_k]]
    return top_texts, top_scores

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
    prompt += "- ตอบให้มั่นใจ ชัดเจน เป็นประโยชน์ที่สุดสำหรับผู้ถาม\n\n"
    prompt += "ท้ายคำตอบทุกครั้ง ต้องมีข้อความ:\n"
    prompt += "\"⚠️ ข้อมูลนี้เป็นความรู้เบื้องต้นเท่านั้น ไม่ใช่คำแนะนำทางกฎหมาย "
    prompt += "กรุณาปรึกษาทนายความหรือหน่วยงานราชการที่เกี่ยวข้องสำหรับกรณีเฉพาะของท่าน\"\n\n"
    prompt += "ตอบเป็นภาษาไทย กระชับ เข้าใจง่ายสำหรับประชาชนทั่วไป"

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    answer = response.content[0].text

    CONFIDENCE_THRESHOLD = 0.3
    if len(scores) == 0 or max(scores) < CONFIDENCE_THRESHOLD:
        log_low_confidence_query(query, answer, top_chunks, max(scores) if scores else 0)

    return answer, top_chunks

# ---------- Pydantic Models (ต้องประกาศก่อนใช้งานด้านล่าง) ----------
class Question(BaseModel):
    query: str

class LogAction(BaseModel):
    log_id: int

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

# ---------- Admin Page & API ----------
@app.get("/admin")
def admin_page(request: Request):
    if not request.session.get("logged_in"):
        return RedirectResponse(url="/admin/login")
    return FileResponse("static/admin.html")

@app.get("/admin/api/logs")
def get_pending_logs(_: bool = Depends(require_login)):
    pending = get_logs(status="pending")   # กรองที่ DB โดยตรง ไม่ต้องดึงทั้งหมดมา filter เอง
    return {"logs": pending}

@app.post("/admin/api/approve")
def approve_log(action: LogAction, _: bool = Depends(require_login)):
    # หา log ที่ตรงกับ id เพื่อเอา query/answer มาต่อเป็น chunk ใหม่
    matching = [l for l in get_logs() if l["id"] == action.log_id]
    if not matching:
        raise HTTPException(status_code=404, detail="Log not found")
    log = matching[0]

    new_chunk = f"{log['query']} — {log['answer']}"
    add_knowledge_chunk(new_chunk)
    db_approve_log(action.log_id)
    rebuild_index()

    return {"status": "approved"}

@app.post("/admin/api/reject")
def reject_log(action: LogAction, _: bool = Depends(require_login)):
    db_reject_log(action.log_id)
    return {"status": "rejected"}


# ---------- เสิร์ฟหน้าเว็บผู้ใช้ ----------
@app.get("/")
def read_root():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
