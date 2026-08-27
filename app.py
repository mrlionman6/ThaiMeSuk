import streamlit as st
import anthropic
from sentence_transformers import SentenceTransformer, CrossEncoder, util
from rank_bm25 import BM25Okapi
from pythainlp.tokenize import word_tokenize
import numpy as np

# ---------- ตั้งค่าหน้าเว็บ ----------
st.set_page_config(page_title="ผู้ช่วยข้อมูลนำเข้า-ส่งออกไทย", page_icon="🇹🇭")
st.title("🇹🇭 ผู้ช่วยข้อมูลนำเข้า-ส่งออกไทย")

# ---------- โหลดโมเดล (cache ไว้ไม่ต้องโหลดซ้ำทุกครั้ง) ----------
@st.cache_resource
def load_models():
    embed_model = SentenceTransformer('intfloat/multilingual-e5-large')
    reranker = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')
    return embed_model, reranker

with st.spinner("กำลังโหลดโมเดล (ครั้งแรกอาจใช้เวลาสักครู่)..."):
    embed_model, reranker = load_models()

client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

# ---------- Knowledge Base ----------
knowledge_base = [
    "ไทยส่งออกข้าวเป็นอันดับต้นๆ ของโลก มูลค่ากว่า 5,000 ล้านดอลลาร์ต่อปี",
    "สินค้าส่งออกหลักของไทยคือเครื่องจักรและอิเล็กทรอนิกส์",
    "การนำเข้าน้ำมันดิบของไทยมาจากตะวันออกกลางเป็นหลัก",
    "กฎระเบียบศุลกากรกำหนดให้ผู้นำเข้าต้องยื่นใบขนสินค้าก่อนนำเข้า",
    "แมวเป็นสัตว์เลี้ยงยอดนิยมในหมู่คนไทย",
    "ประเทศคู่ค้าสำคัญของไทยคือจีน สหรัฐฯ และญี่ปุ่น"
]

@st.cache_resource
def build_index(_embed_model, kb):
    kb_embeddings = _embed_model.encode(kb)
    tokenized_kb = [word_tokenize(doc, engine="newmm") for doc in kb]
    bm25 = BM25Okapi(tokenized_kb)
    return kb_embeddings, bm25

kb_embeddings, bm25 = build_index(embed_model, knowledge_base)

# ---------- ฟังก์ชัน RAG Pipeline ----------
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

    prompt = f"""คุณเป็นผู้เชี่ยวชาญด้านการค้าระหว่างประเทศของไทย
ใช้ข้อมูลอ้างอิงต่อไปนี้ตอบคำถาม หากข้อมูลไม่เพียงพอให้บอกตรงๆ ว่าไม่มีข้อมูล ห้ามเดาเอง

ข้อมูลอ้างอิง:
{context}

คำถาม: {query}

ตอบเป็นภาษาเดียวกับคำถาม กระชับ ชัดเจน"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text, top_chunks

# ---------- UI ----------
user_input = st.text_input("พิมพ์คำถามเกี่ยวกับการนำเข้า-ส่งออกไทย")

if user_input:
    with st.spinner("กำลังค้นหาและวิเคราะห์..."):
        answer, sources = rag_answer(user_input)

    st.write("**คำตอบ:**")
    st.write(answer)

    with st.expander("📚 แหล่งข้อมูลที่ใช้อ้างอิง"):
        for i, s in enumerate(sources):
            st.write(f"{i+1}. {s}")
