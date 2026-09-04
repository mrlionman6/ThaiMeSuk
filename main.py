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
    get_user_by_username,
    get_user_by_id,
    update_user_password,
    update_user_nickname,
    delete_user,
    save_security_answers,
    get_security_answers_for_user,
    get_pending_user_requests,
    approve_user_request,
    reject_user_request,
    get_approved_users,
    update_user_role,
    block_user,
    unblock_user,
    create_chat_session,
    touch_chat_session,
    get_user_chats,
    get_chat_session,
    add_chat_message,
    get_chat_messages,
    delete_chat_session,
)

import os
import io
import json
import time
import string
import random
import bcrypt
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
import anthropic
from sentence_transformers import SentenceTransformer, CrossEncoder
from rank_bm25 import BM25Okapi
from pythainlp.tokenize import word_tokenize
import numpy as np
from starlette.middleware.sessions import SessionMiddleware
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "change-this-secret-key"),
    max_age=None,  # ไม่ตั้งวันหมดอายุยาว — ให้เป็น session cookie ที่หายไปเมื่อปิด browser จริง
)

# ---------- Security questions สำหรับลืมรหัสผ่าน (ไม่ใช้อีเมล) ----------
SECURITY_QUESTIONS = {
    1: "ชื่อสัตว์เลี้ยงตัวแรกของคุณคืออะไร",
    2: "โรงเรียนประถมที่คุณเรียนชื่ออะไร",
    3: "ชื่อกลางของคุณ (ถ้ามี) คืออะไร",
    4: "อาหารจานโปรดตอนเด็กของคุณคืออะไร",
    5: "ชื่อเพื่อนสนิทคนแรกของคุณคือใคร",
    6: "คุณเกิดที่จังหวัดอะไร",
    7: "ชื่อครูที่คุณชอบที่สุดคือใคร",
    8: "รถคันแรกที่คุณขับ (หรืออยากได้) ยี่ห้ออะไร",
    9: "เมืองในฝันที่อยากไปเที่ยวคือที่ไหน",
    10: "ของเล่นชิ้นโปรดตอนเด็กของคุณคืออะไร",
}
REQUIRED_SECURITY_ANSWERS = 5  # ต้องเลือกตอบให้ครบเท่านี้ตอนสมัคร
SESSION_TIMEOUT_SECONDS = 8 * 60 * 60  # auto-logout ถ้าไม่ใช้งานเกิน 8 ชั่วโมง
VALID_ROLES = (1, 2, 3)  # ระดับสิทธิ์ผู้ใช้ — ความหมายจริงจะถูกกำหนดทีหลังตอนจำกัด prompt ตามสิทธิ์
CAPTCHA_CHARS = string.ascii_uppercase + string.digits  # ตัดตัวที่สับสนง่ายออก (O/0, I/1) เพื่อความชัดเจน
CAPTCHA_CHARS = "".join(c for c in CAPTCHA_CHARS if c not in "O0I1")

# ---------- Conversational RAG: จำกัดขนาดประวัติที่ส่งกลับทุกครั้ง กัน token บวมเมื่อแชทยาวขึ้น ----------
MAX_HISTORY_MESSAGES = 10  # 5 คู่ (user+assistant) ล่าสุด ที่ส่งให้ Claude ตัวจริงดูประกอบตอบ
REWRITER_HISTORY_MESSAGES = 6  # 3 คู่ล่าสุด ที่ส่งให้ Query Rewriter ดูประกอบ (ไม่ต้องเยอะเท่า main context)

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
    """dependency สำหรับ endpoint ที่ต้อง login เป็น user (ไม่ใช่ admin) — คืนค่า user_id
    เช็ค inactivity timeout ด้วย (8 ชม.) — ถ้าเกินจะ logout อัตโนมัติ"""
    user_id = get_active_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user_id

def _clear_user_session(request: Request):
    """ล้าง session ของ user (ไม่แตะ admin session) — เรียกรวมจุดเดียวกันทุกที่ที่ต้อง logout"""
    request.session.pop("user_id", None)
    request.session.pop("last_active", None)
    request.session.pop("session_version", None)

def get_active_user_id(request: Request) -> Optional[int]:
    """คืน user_id ถ้า session ยัง valid ทั้ง 3 เงื่อนไข:
    1. ไม่เกิน SESSION_TIMEOUT_SECONDS นับจากใช้งานล่าสุด (inactivity timeout)
    2. บัญชียัง status='approved' อยู่ (ไม่ถูกลบ/block/reject)
    3. session_version ใน cookie ตรงกับใน DB (ถ้า admin เพิ่งกด block/unblock เลขจะไม่ตรง = บังคับ logout)
    เรียกใช้แทนการอ่าน request.session.get('user_id') ตรงๆ ทุกจุดที่เกี่ยวกับ user auth"""
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    last_active = request.session.get("last_active")
    now = time.time()
    if last_active is not None and (now - last_active) > SESSION_TIMEOUT_SECONDS:
        _clear_user_session(request)
        return None

    user = get_user_by_id(user_id)
    if user is None or user["status"] != "approved":
        _clear_user_session(request)
        return None
    if request.session.get("session_version") != user["session_version"]:
        _clear_user_session(request)
        return None

    request.session["last_active"] = now
    return user_id

def normalize_answer(answer: str) -> str:
    """ทำให้คำตอบ security question เทียบกันได้ไม่ติดเรื่องตัวพิมพ์เล็ก-ใหญ่/ช่องว่างหัวท้าย
    เรียกก่อน hash เสมอ ทั้งตอนสมัครและตอนเช็คตอนลืมรหัสผ่าน"""
    return answer.strip().lower()

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

def rewrite_query_for_retrieval(query: str, history: list) -> str:
    """ใช้ Claude Haiku เขียนคำถามที่กำกวม/อ้างอิงบริบทก่อนหน้า (เช่น 'แล้วอันนี้ล่ะ')
    ให้เป็นประโยคสมบูรณ์ในตัวเอง ก่อนนำไปค้นหาใน Knowledge Base — แก้ปัญหา RAG ทั่วไปที่มักพลาด
    เวลาคำถามถูกตัดตอนมาจากบทสนทนา (ไม่มีบริบทพอให้ embedding/BM25 ค้นแม่น)

    สำคัญ: ถ้าคำถามใหม่เป็นคนละเรื่องกับที่คุยไว้ก่อนหน้า (user เปลี่ยนหัวข้อ) ต้องคืนคำถามเดิม
    กลับไปตรงๆ ไม่งั้นจะกลายเป็นบั๊กตรงข้าม (ยึดติดบริบทเก่าจนตอบเพี้ยนเรื่องใหม่)"""
    if not history:
        return query  # เทิร์นแรกของแชทไม่มีบริบทให้อ้างอิง ไม่ต้องเสีย API call รีไรท์

    recent = history[-REWRITER_HISTORY_MESSAGES:]
    history_text = "\n".join(
        f"{'ผู้ใช้' if m['role'] == 'user' else 'ผู้ช่วย'}: {m['content']}" for m in recent
    )

    rewrite_prompt = (
        "ต่อไปนี้คือบทสนทนาก่อนหน้า และคำถามใหม่ล่าสุดของผู้ใช้\n\n"
        f"บทสนทนาก่อนหน้า:\n{history_text}\n\n"
        f"คำถามใหม่ล่าสุด: {query}\n\n"
        "หน้าที่ของคุณ:\n"
        "- ถ้าคำถามใหม่นี้อ้างอิงถึงสิ่งที่คุยไว้ก่อนหน้า (เช่นใช้คำว่า \"แล้ว...ล่ะ\", \"อันนี้\", \"ถ้าเป็น...ล่ะ\") "
        "ให้เขียนคำถามใหม่เป็นประโยคที่สมบูรณ์ในตัวเอง ไม่ต้องพึ่งบริบทก่อนหน้าอีกต่อไป\n"
        "- แต่ถ้าคำถามใหม่เป็นคนละเรื่องกับที่คุยไว้เลย (เปลี่ยนหัวข้อ) ให้คืนคำถามเดิมกลับไปตรงๆ ไม่ต้องแก้ไขอะไร\n"
        "- ตอบกลับมาแค่คำถามที่ได้เท่านั้น ห้ามมีคำอธิบายหรือข้อความอื่นเพิ่มเติม"
    )

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        messages=[{"role": "user", "content": rewrite_prompt}],
    )
    rewritten = response.content[0].text.strip()
    print(f"[QueryRewriter] original={query!r} -> rewritten={rewritten!r}")  # เช็คผลผ่าน Railway logs ได้
    return rewritten if rewritten else query

def rag_answer(query, history=None):
    history = history or []

    search_query = rewrite_query_for_retrieval(query, history)
    candidates = hybrid_search(search_query, k=5)
    top_chunks, scores = rerank_with_scores(search_query, candidates, top_k=3)
    context = "\n".join([f"- {c}" for c in top_chunks])

    system_prompt = (
        "คุณเป็นผู้ช่วยให้ความรู้กฎหมายเบื้องต้นแก่ประชาชนไทย\n"
        "- ถ้าข้อมูลอ้างอิงที่ให้มาตรงกับคำถาม ให้ใช้ข้อมูลนั้นเป็นหลัก\n"
        "- ถ้าข้อมูลอ้างอิงไม่ครอบคลุมหรือไม่มีรายละเอียดพอ ให้ใช้ความรู้ทั่วไปของคุณตอบเสริมให้ครบถ้วนที่สุด "
        "โดยไม่ต้องบอกผู้ใช้ว่าข้อมูลอ้างอิงไม่พอ\n"
        "- ตอบให้มั่นใจ ชัดเจน เป็นประโยชน์ที่สุดสำหรับผู้ถาม\n"
        "- ห้ามใส่ข้อความ disclaimer หรือคำเตือนใดๆ ท้ายคำตอบเอง ระบบจะเป็นผู้เพิ่มให้เองภายหลัง\n"
        "- ตอบเป็นภาษาไทย กระชับ เข้าใจง่ายสำหรับประชาชนทั่วไป\n"
        "- ถ้าคำถามล่าสุดอ้างอิงถึงสิ่งที่คุยไว้ก่อนหน้าในบทสนทนานี้ ให้ใช้บริบทนั้นประกอบการตอบด้วย"
    )

    current_turn_content = (
        "ข้อมูลอ้างอิงที่อาจเกี่ยวข้อง (ใช้ประกอบถ้าตรงกับคำถาม):\n" + context + "\n\n"
        "คำถาม: " + query
    )

    # ต่อประวัติสนทนาเดิม (ถ้ามี) เข้าเป็น multi-turn messages ก่อนคำถามล่าสุด
    # ใช้แค่ query ต้นฉบับ (ไม่ใช่ search_query ที่ rewrite แล้ว) เพราะนี่คือสิ่งที่ user พิมพ์จริง
    recent_history = history[-MAX_HISTORY_MESSAGES:] if history else []
    messages = [{"role": m["role"], "content": m["content"]} for m in recent_history]
    messages.append({"role": "user", "content": current_turn_content})

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        system=system_prompt,
        messages=messages,
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

class SecurityAnswerInput(BaseModel):
    question_id: int
    answer: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    nickname: str
    requested_role: int
    captcha_answer: str
    security_answers: list[SecurityAnswerInput]

class LoginRequest(BaseModel):
    username: str
    password: str

class ChatCreateRequest(BaseModel):
    title: Optional[str] = None

class ForgotPasswordQuestionsRequest(BaseModel):
    username: str

class ForgotPasswordResetRequest(BaseModel):
    username: str
    answers: list[SecurityAnswerInput]
    new_password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class DeleteAccountRequest(BaseModel):
    password: str

class UpdateNicknameRequest(BaseModel):
    nickname: str

class ApproveUserRequest(BaseModel):
    granted_role: int

class UpdateUserRoleRequest(BaseModel):
    role: int

# ---------- User API ----------
@app.post("/ask")
def ask_question(question: Question, request: Request):
    user_id = get_active_user_id(request)
    chat_id = question.chat_id

    # ดึงประวัติสนทนา "ก่อน" เรียก rag_answer เพราะต้องใช้ตอน rewrite query + ส่งเป็น multi-turn context
    # จำกัดเฉพาะ user ที่ login เท่านั้น (guest ไม่มี chat_id/ประวัติผูกกับ DB ให้ดึง)
    history = []
    if user_id and chat_id:
        # เช็คว่าแชทนี้เป็นของ user คนนี้จริง กัน user คนอื่นยัดคำถามใส่แชทของคนอื่น
        if get_chat_session(chat_id, user_id) is None:
            raise HTTPException(status_code=404, detail="ไม่พบแชทนี้")
        history = get_chat_messages(chat_id)

    answer, sources = rag_answer(question.query, history=history)

    if user_id:
        if chat_id is None:
            # ยังไม่มีแชทอยู่ (ผู้ใช้เพิ่งเริ่มถามคำถามแรก) — สร้างแชทใหม่ ตั้งชื่อจากคำถามแรก
            title = question.query.strip()[:50] or "แชทใหม่"
            chat_id = create_chat_session(user_id, title=title)

        add_chat_message(chat_id, "user", question.query)
        add_chat_message(chat_id, "assistant", answer)
        touch_chat_session(chat_id)

    return {"answer": answer, "sources": sources, "chat_id": chat_id}

# ---------- Auth API (สำหรับผู้ใช้ทั่วไป — แยกจาก admin) ----------
@app.get("/api/auth/security-questions")
def list_security_questions():
    """คืนรายการคำถามทั้ง 10 ข้อ (ไม่มีคำตอบ) — ใช้ตอน render ฟอร์มสมัคร"""
    return {"questions": [{"id": qid, "text": text} for qid, text in SECURITY_QUESTIONS.items()]}

@app.get("/api/auth/captcha")
def get_captcha(request: Request):
    """สร้างภาพ CAPTCHA แบบง่าย (วาดเองด้วย Pillow ไม่พึ่ง third-party service)
    เก็บคำตอบไว้ใน session ชั่วคราว — ใช้ครั้งเดียวแล้วลบทิ้งตอน verify"""
    captcha_text = "".join(random.choices(CAPTCHA_CHARS, k=5))
    request.session["captcha_text"] = captcha_text

    img = Image.new("RGB", (150, 50), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    for i, ch in enumerate(captcha_text):
        x = 12 + i * 26 + random.randint(-3, 3)
        y = 15 + random.randint(-5, 5)
        draw.text((x, y), ch, fill=(20, 20, 20), font=font)

    # เส้นรบกวนพื้นหลัง กัน bot อ่านง่ายเกินไป
    for _ in range(6):
        x1, y1 = random.randint(0, 150), random.randint(0, 50)
        x2, y2 = random.randint(0, 150), random.randint(0, 50)
        draw.line([(x1, y1), (x2, y2)], fill=(190, 190, 190), width=1)

    img = img.resize((300, 100))  # ขยาย 2 เท่า ให้ตัวอักษรจากฟอนต์ bitmap เล็กๆ อ่านง่ายขึ้น

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

@app.post("/api/auth/register")
def register(body: RegisterRequest, request: Request):
    username = body.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="ชื่อผู้ใช้ต้องมีอย่างน้อย 3 ตัวอักษร")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="รหัสผ่านต้องมีอย่างน้อย 8 ตัวอักษร")

    nickname = body.nickname.strip()
    if not nickname:
        raise HTTPException(status_code=400, detail="กรุณาตั้งชื่อเล่น (nickname)")

    if body.requested_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="ระดับสิทธิ์ที่ขอไม่ถูกต้อง")

    # เช็ค CAPTCHA ก่อนอย่างอื่น — ใช้ครั้งเดียวแล้วลบทิ้งทันที กันเดาซ้ำ/replay
    stored_captcha = request.session.get("captcha_text")
    request.session.pop("captcha_text", None)
    if not stored_captcha or body.captcha_answer.strip().upper() != stored_captcha:
        raise HTTPException(status_code=400, detail="กรอกรหัสยืนยันภาพ (CAPTCHA) ไม่ถูกต้อง")

    if len(body.security_answers) != REQUIRED_SECURITY_ANSWERS:
        raise HTTPException(
            status_code=400,
            detail=f"ต้องเลือกตอบคำถามกันลืมรหัสผ่านให้ครบ {REQUIRED_SECURITY_ANSWERS} ข้อ",
        )

    question_ids = [a.question_id for a in body.security_answers]
    if len(set(question_ids)) != len(question_ids):
        raise HTTPException(status_code=400, detail="เลือกคำถามซ้ำกันไม่ได้")
    if any(qid not in SECURITY_QUESTIONS for qid in question_ids):
        raise HTTPException(status_code=400, detail="มีคำถามที่ไม่ถูกต้องอยู่ในรายการ")
    if any(not a.answer.strip() for a in body.security_answers):
        raise HTTPException(status_code=400, detail="ตอบคำถามกันลืมรหัสผ่านให้ครบทุกข้อที่เลือก")

    password_hash = hash_password(body.password)
    result = create_user(username, password_hash, nickname, body.requested_role)
    if result == "username_taken":
        raise HTTPException(status_code=409, detail="ชื่อผู้ใช้นี้มีคนใช้แล้ว")
    if result == "nickname_taken":
        raise HTTPException(status_code=409, detail="ชื่อเล่นนี้มีคนใช้แล้ว กรุณาเลือกชื่อเล่นอื่น")
    new_id = result

    answer_records = [
        {"question_id": a.question_id, "answer_hash": hash_password(normalize_answer(a.answer))}
        for a in body.security_answers
    ]
    save_security_answers(new_id, answer_records)

    # ไม่ auto-login แล้ว — ต้องรอ admin อนุมัติก่อนถึง login ได้
    return {"status": "pending_approval"}

@app.post("/api/auth/login")
def user_login(body: LoginRequest, request: Request):
    username = body.username.strip()
    user = get_user_by_username(username)
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    if user["status"] == "pending":
        raise HTTPException(status_code=403, detail="บัญชีนี้ยังรอการอนุมัติจากผู้ดูแลระบบ")
    if user["status"] == "rejected":
        raise HTTPException(status_code=403, detail="คำขอสมัครสมาชิกนี้ถูกปฏิเสธ")
    if user["status"] == "blocked":
        raise HTTPException(status_code=403, detail="บัญชีนี้ถูกระงับการใช้งานชั่วคราว กรุณาติดต่อผู้ดูแลระบบ")

    request.session["user_id"] = user["id"]
    request.session["last_active"] = time.time()
    request.session["session_version"] = user["session_version"]
    return {
        "status": "logged_in",
        "user": {"id": user["id"], "username": user["username"], "nickname": user["nickname"], "role": user["role"]},
    }

@app.post("/api/auth/logout")
def user_logout(request: Request):
    _clear_user_session(request)
    return {"status": "logged_out"}

@app.get("/api/auth/me")
def auth_me(request: Request):
    user_id = get_active_user_id(request)
    if not user_id:
        return {"logged_in": False}
    user = get_user_by_id(user_id)
    if user is None:
        _clear_user_session(request)  # user ถูกลบไปแล้วแต่ session ยังค้าง — ล้างทิ้ง
        return {"logged_in": False}
    return {"logged_in": True, "user": user}

# ---------- ลืมรหัสผ่าน (ผ่าน security questions ไม่ใช้อีเมล) ----------
@app.post("/api/auth/forgot-password/questions")
def forgot_password_questions(body: ForgotPasswordQuestionsRequest):
    """สุ่ม 2 ข้อจาก 5 ข้อที่ user เคยตั้งไว้ตอนสมัคร มาให้ตอบยืนยันตัวตน"""
    username = body.username.strip()
    user = get_user_by_username(username)
    if user is None:
        # ไม่บอกตรงๆ ว่าไม่เจอ username กันคนสุ่มเช็คว่า username ไหนมีในระบบ (user enumeration)
        raise HTTPException(status_code=404, detail="ไม่พบบัญชีนี้ หรือข้อมูลไม่ถูกต้อง")

    answers = get_security_answers_for_user(user["id"])
    if len(answers) < 2:
        raise HTTPException(status_code=400, detail="บัญชีนี้ยังไม่มีคำถามกันลืมรหัสผ่านเพียงพอ")

    chosen = random.sample(answers, 2)
    questions = [
        {"question_id": a["question_id"], "text": SECURITY_QUESTIONS.get(a["question_id"], "")}
        for a in chosen
    ]
    return {"questions": questions}

@app.post("/api/auth/forgot-password/reset")
def forgot_password_reset(body: ForgotPasswordResetRequest):
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="รหัสผ่านใหม่ต้องมีอย่างน้อย 8 ตัวอักษร")
    if len(body.answers) != 2:
        raise HTTPException(status_code=400, detail="ต้องตอบคำถามให้ครบ 2 ข้อ")

    username = body.username.strip()
    user = get_user_by_username(username)
    if user is None:
        raise HTTPException(status_code=404, detail="ไม่พบบัญชีนี้ หรือข้อมูลไม่ถูกต้อง")

    stored_answers = {a["question_id"]: a["answer_hash"] for a in get_security_answers_for_user(user["id"])}

    for given in body.answers:
        stored_hash = stored_answers.get(given.question_id)
        if stored_hash is None or not verify_password(normalize_answer(given.answer), stored_hash):
            raise HTTPException(status_code=401, detail="คำตอบไม่ถูกต้อง")

    new_hash = hash_password(body.new_password)
    update_user_password(user["id"], new_hash)
    return {"status": "password_reset"}

# ---------- Profile: เปลี่ยนรหัสผ่าน / เปลี่ยน nickname / ลบบัญชี (ต้อง login) ----------
@app.post("/api/auth/change-password")
def change_password(body: ChangePasswordRequest, user_id: int = Depends(require_user)):
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="รหัสผ่านใหม่ต้องมีอย่างน้อย 8 ตัวอักษร")

    user = get_user_by_id(user_id)
    full_user = get_user_by_username(user["username"])  # ต้องดึงผ่าน username เพราะ get_user_by_id ไม่คืน password_hash
    if not verify_password(body.current_password, full_user["password_hash"]):
        raise HTTPException(status_code=401, detail="รหัสผ่านปัจจุบันไม่ถูกต้อง")

    new_hash = hash_password(body.new_password)
    update_user_password(user_id, new_hash)
    return {"status": "password_changed"}

@app.post("/api/auth/update-nickname")
def update_nickname(body: UpdateNicknameRequest, user_id: int = Depends(require_user)):
    nickname = body.nickname.strip()
    if not nickname:
        raise HTTPException(status_code=400, detail="ชื่อเล่นห้ามว่างเปล่า")
    result = update_user_nickname(user_id, nickname)
    if result == "nickname_taken":
        raise HTTPException(status_code=409, detail="ชื่อเล่นนี้มีคนใช้แล้ว กรุณาเลือกชื่อเล่นอื่น")
    if result == "not_found":
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้นี้")
    return {"status": "nickname_updated", "nickname": nickname}

@app.delete("/api/auth/account")
def delete_account(body: DeleteAccountRequest, request: Request, user_id: int = Depends(require_user)):
    user = get_user_by_id(user_id)
    full_user = get_user_by_username(user["username"])
    if not verify_password(body.password, full_user["password_hash"]):
        raise HTTPException(status_code=401, detail="รหัสผ่านไม่ถูกต้อง")

    delete_user(user_id)  # ON DELETE CASCADE ลบ chat/security answers ที่เกี่ยวข้องทั้งหมดให้เอง
    _clear_user_session(request)
    return {"status": "account_deleted"}

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

# ---------- Admin API (คำขอสมัครสมาชิก — แท็บใหม่) ----------
@app.get("/admin/api/user-requests")
def list_user_requests(page: int = 1, page_size: int = 10, _: bool = Depends(require_login)):
    result = get_pending_user_requests(page=page, page_size=page_size)
    return {"requests": result["items"], "total": result["total"], "page": page, "page_size": page_size}

@app.post("/admin/api/user-requests/{user_id}/approve")
def approve_user_request_endpoint(user_id: int, body: ApproveUserRequest, _: bool = Depends(require_login)):
    if body.granted_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="ระดับสิทธิ์ไม่ถูกต้อง")
    ok = approve_user_request(user_id, body.granted_role)
    if not ok:
        raise HTTPException(status_code=404, detail="ไม่พบคำขอนี้ หรือถูกตัดสินใจไปแล้ว")
    return {"status": "approved"}

@app.post("/admin/api/user-requests/{user_id}/reject")
def reject_user_request_endpoint(user_id: int, _: bool = Depends(require_login)):
    ok = reject_user_request(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="ไม่พบคำขอนี้ หรือถูกตัดสินใจไปแล้ว")
    return {"status": "rejected"}

# ---------- Admin API (จัดการบัญชีผู้ใช้ที่อนุมัติแล้ว — แท็บใหม่) ----------
@app.get("/admin/api/users")
def list_users(page: int = 1, page_size: int = 10, _: bool = Depends(require_login)):
    result = get_approved_users(page=page, page_size=page_size)
    return {"users": result["items"], "total": result["total"], "page": page, "page_size": page_size}

@app.put("/admin/api/users/{user_id}")
def update_user_role_endpoint(user_id: int, body: UpdateUserRoleRequest, _: bool = Depends(require_login)):
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="ระดับสิทธิ์ไม่ถูกต้อง")
    ok = update_user_role(user_id, body.role)
    if not ok:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้นี้")
    return {"status": "updated"}

@app.post("/admin/api/users/{user_id}/block")
def block_user_endpoint(user_id: int, _: bool = Depends(require_login)):
    """ระงับบัญชีชั่วคราว (เช่น สงสัยว่าโดน hack) — บังคับ logout session เดิมทุกที่ทันที
    ผ่านกลไก session_version (ดู get_active_user_id) ไม่ใช่การเตะออกแบบ real-time"""
    ok = block_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้นี้ หรือสถานะไม่ใช่ approved อยู่แล้ว")
    return {"status": "blocked"}

@app.post("/admin/api/users/{user_id}/unblock")
def unblock_user_endpoint(user_id: int, _: bool = Depends(require_login)):
    ok = unblock_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้นี้ หรือสถานะไม่ใช่ blocked อยู่")
    return {"status": "unblocked"}

@app.delete("/admin/api/users/{user_id}")
def admin_delete_user_endpoint(user_id: int, _: bool = Depends(require_login)):
    """ลบบัญชีถาวร (เช่น ยืนยันแล้วว่าโดน hack จริง) — ON DELETE CASCADE ลบ
    chat/security answers ที่เกี่ยวข้องทั้งหมดให้เอง เหมือนตอน user ลบบัญชีตัวเอง"""
    ok = delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้นี้")
    return {"status": "deleted"}


# ---------- เสิร์ฟหน้าเว็บผู้ใช้ ----------
@app.get("/")
def read_root():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
