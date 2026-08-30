import os
import numpy as np
import json
import anthropic

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import anthropic
from sentence_transformers import SentenceTransformer, CrossEncoder, util
from rank_bm25 import BM25Okapi
from pythainlp.tokenize import word_tokenize


app = FastAPI()

# ---------- โหลดโมเดล (ครั้งเดียวตอนเริ่มเซิร์ฟเวอร์) ----------
print("กำลังโหลดโมเดล...")
embed_model = SentenceTransformer('intfloat/multilingual-e5-large')
reranker = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')
print("โหลดโมเดลสำเร็จ")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ---------- Knowledge Base ----------
with open("knowledge_base.json", "r", encoding="utf-8") as f:
    knowledge_base = json.load(f)

# ---------- สร้าง Index (Embedding + BM25) ----------
kb_embeddings = embed_model.encode(knowledge_base)
tokenized_kb = [word_tokenize(doc, engine="newmm") for doc in knowledge_base]
bm25 = BM25Okapi(tokenized_kb)

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

def rerank(query, candidates, top_k=3):
    pairs = [[query, c] for c in candidates]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    return [text for text, score in ranked[:top_k]]

def rag_answer(query):
    candidates = hybrid_search(query, k=5)
    top_chunks = rerank(query, candidates, top_k=3)
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
    return response.content[0].text, top_chunks

# ---------- API Endpoint ----------
class Question(BaseModel):
    query: str

@app.post("/ask") # ← ต้องตรงกับที่ script.js เรียก fetch("/ask")
def ask_question(question: Question):
    answer, sources = rag_answer(question.query)
    return {"answer": answer, "sources": sources}

# ---------- เสิร์ฟหน้าเว็บ (static files) ----------
@app.get("/")
def read_root():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
