import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import anthropic
from sentence_transformers import SentenceTransformer, CrossEncoder, util
from rank_bm25 import BM25Okapi
from pythainlp.tokenize import word_tokenize
import numpy as np

app = FastAPI()

# ---------- โหลดโมเดล (ครั้งเดียวตอนเริ่มเซิร์ฟเวอร์) ----------
print("กำลังโหลดโมเดล...")
embed_model = SentenceTransformer('intfloat/multilingual-e5-large')
reranker = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')
print("โหลดโมเดลสำเร็จ")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ---------- Knowledge Base ----------
knowledge_base = [
    "บุคคลธรรมดาที่มีเงินได้สุทธิเกิน 150,000 บาทต่อปี มีหน้าที่ต้องยื่นแบบแสดงรายการภาษีเงินได้บุคคลธรรมดา",
    "ภาษีเงินได้บุคคลธรรมดาของไทยใช้อัตราก้าวหน้า (progressive rate) ยิ่งมีเงินได้สุทธิสูง อัตราภาษียิ่งสูงขึ้นเป็นขั้นบันได",
    "ค่าลดหย่อนภาษีที่พบบ่อย ได้แก่ ค่าลดหย่อนส่วนตัว ค่าลดหย่อนคู่สมรส ค่าลดหย่อนบุตร และเบี้ยประกันชีวิต",
    "ผู้มีเงินได้จากการขายอสังหาริมทรัพย์ ต้องเสียภาษีเงินได้จากการขายอสังหาริมทรัพย์ โดยคำนวณจากราคาประเมินทุนทรัพย์",
    "ภาษีมูลค่าเพิ่ม (VAT) จัดเก็บจากการขายสินค้าและบริการ ผู้ประกอบการที่มีรายได้เกินเกณฑ์ที่กฎหมายกำหนดต้องจดทะเบียนภาษีมูลค่าเพิ่ม",
    "การยื่นภาษีเงินได้บุคคลธรรมดาสามารถยื่นได้ทั้งแบบกระดาษที่สำนักงานสรรพากร หรือยื่นออนไลน์ผ่านเว็บไซต์กรมสรรพากร",
    "ภาษีที่ดินและสิ่งปลูกสร้าง จัดเก็บจากเจ้าของที่ดินหรือสิ่งปลูกสร้าง โดยอัตราภาษีแตกต่างกันตามประเภทการใช้ประโยชน์ เช่น ที่อยู่อาศัย เกษตรกรรม หรือพาณิชยกรรม",
    "การซื้อขายที่ดินต้องทำเป็นหนังสือและจดทะเบียนต่อพนักงานเจ้าหน้าที่ ณ สำนักงานที่ดิน มิฉะนั้นการซื้อขายจะเป็นโมฆะ",
    "ค่าธรรมเนียมการโอนกรรมสิทธิ์ที่ดิน คิดจากราคาประเมินทุนทรัพย์ของกรมที่ดิน ซึ่งอาจแตกต่างจากราคาซื้อขายจริง",
    "โฉนดที่ดิน (น.ส.4) เป็นเอกสารสิทธิ์ที่แสดงกรรมสิทธิ์ในที่ดินอย่างสมบูรณ์ตามกฎหมาย",
    "การรับมรดกที่ดิน ทายาทต้องดำเนินการจดทะเบียนโอนมรดกที่สำนักงานที่ดิน โดยต้องมีเอกสารยืนยันสิทธิ์การเป็นทายาท",
    "การเช่าที่ดินหรืออสังหาริมทรัพย์เกิน 3 ปี ต้องทำเป็นหนังสือและจดทะเบียนต่อพนักงานเจ้าหน้าที่ มิฉะนั้นจะฟ้องร้องบังคับได้เพียง 3 ปี",
    "ที่ดินที่ไม่มีเอกสารสิทธิ์ เช่น ส.ป.ก. หรือที่ดินมือเปล่า มีข้อจำกัดในการซื้อขายหรือโอนกรรมสิทธิ์มากกว่าที่ดินที่มีโฉนด",
    "การจดทะเบียนบริษัทจำกัดต้องมีผู้ก่อการตั้งแต่ 2 คนขึ้นไป และต้องจดทะเบียนหนังสือบริคณห์สนธิกับกรมพัฒนาธุรกิจการค้า",
    "การประกอบธุรกิจในนามบุคคลธรรมดา (เจ้าของคนเดียว) ไม่ต้องจดทะเบียนนิติบุคคล แต่เจ้าของต้องรับผิดชอบหนี้สินทั้งหมดด้วยทรัพย์สินส่วนตัว",
    "บริษัทจำกัดเป็นนิติบุคคลแยกต่างหากจากผู้ถือหุ้น ผู้ถือหุ้นรับผิดชอบหนี้สินจำกัดเพียงเท่าจำนวนเงินค่าหุ้นที่ยังส่งใช้ไม่ครบ",
    "สัญญาทางธุรกิจควรระบุรายละเอียดให้ชัดเจน เช่น คู่สัญญา ขอบเขตงาน ระยะเวลา และเงื่อนไขการชำระเงิน เพื่อป้องกันข้อพิพาท",
    "ธุรกิจที่มีรายได้เกินเกณฑ์ที่กฎหมายกำหนดต้องจัดทำบัญชีและงบการเงินตามมาตรฐานการบัญชี และยื่นต่อกรมพัฒนาธุรกิจการค้า",
    "การเลิกกิจการบริษัทจำกัดต้องผ่านมติที่ประชุมผู้ถือหุ้น และดำเนินการชำระบัญชีก่อนจดทะเบียนเลิกบริษัทอย่างสมบูรณ์",
    "ความผิดฐานลักทรัพย์ตามประมวลกฎหมายอาญา มีโทษจำคุกและปรับ โดยโทษจะสูงขึ้นหากเป็นการลักทรัพย์ในเวลากลางคืนหรือโดยใช้กำลังประทุษร้าย",
    "คดีแพ่งเป็นข้อพิพาทระหว่างเอกชนกับเอกชน เช่น สัญญา ละเมิด โดยศาลจะสั่งให้ชดใช้ค่าเสียหายเป็นตัวเงิน ไม่ใช่โทษทางอาญา",
    "คดีอาญาเป็นความผิดที่กระทบต่อรัฐและสังคม เช่น ลักทรัพย์ ทำร้ายร่างกาย ซึ่งรัฐเป็นผู้ฟ้องร้องผ่านพนักงานอัยการ",
    "อายุความในการฟ้องร้องคดีแพ่งทั่วไปมีกำหนด 10 ปี เว้นแต่กฎหมายกำหนดอายุความสั้นกว่านั้นไว้เป็นการเฉพาะ",
    "ผู้เสียหายในคดีอาญาสามารถแจ้งความร้องทุกข์ต่อพนักงานสอบสวน ณ สถานีตำรวจท้องที่เกิดเหตุ หรือท้องที่ที่ผู้เสียหายอาศัยอยู่",
    "การไกล่เกลี่ยข้อพิพาท เป็นทางเลือกในการระงับข้อพิพาททางแพ่งโดยไม่ต้องผ่านกระบวนการพิจารณาคดีในศาลเต็มรูปแบบ"
]

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

@app.post("/ask")
def ask_question(question: Question):
    answer, sources = rag_answer(question.query)
    return {"answer": answer, "sources": sources}

# ---------- เสิร์ฟหน้าเว็บ (static files) ----------
@app.get("/")
def read_root():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
