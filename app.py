import streamlit as st
import anthropic
from sentence_transformers import SentenceTransformer, CrossEncoder, util
from rank_bm25 import BM25Okapi
from pythainlp.tokenize import word_tokenize
import numpy as np

st.set_page_config(page_title="ผู้ช่วยความรู้กฎหมายเบื้องต้น", page_icon="⚖️")
st.title("⚖️ ผู้ช่วยความรู้กฎหมายเบื้องต้นแก่ประชาชน")

@st.cache_resource
def load_models():
    embed_model = SentenceTransformer('intfloat/multilingual-e5-large')
    reranker = CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')
    return embed_model, reranker

with st.spinner("กำลังโหลดโมเดล..."):
    embed_model, reranker = load_models()

client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

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
    prompt += "ข้อมูลอ้างอิงที่มี:\n" + context + "\n\n"
    prompt += "คำถาม: " + query + "\n\n"
    prompt += "กฎการตอบที่ต้องปฏิบัติตามเคร่งครัด:\n"
    prompt += "1. ตอบจากข้อมูลอ้างอิงข้างต้นเท่านั้น ห้ามเดาหรือใช้ความรู้ทั่วไปแทน\n"
    prompt += "2. ถ้าข้อมูลอ้างอิงไม่ครอบคลุมคำถาม ให้บอกตรงๆ ว่าไม่มีข้อมูลในส่วนนี้\n"
    prompt += "3. ห้ามระบุตัวเลข (อัตราภาษี ค่าธรรมเนียม) ที่ไม่มีในข้อมูลอ้างอิงเด็ดขาด\n"
    prompt += "4. ท้ายคำตอบทุกครั้ง ต้องมีข้อความ:\n"
    prompt += "   \"⚠️ ข้อมูลนี้เป็นความรู้เบื้องต้นเท่านั้น ไม่ใช่คำแนะนำทางกฎหมาย "
    prompt += "กรุณาปรึกษาทนายความหรือหน่วยงานราชการที่เกี่ยวข้องสำหรับกรณีเฉพาะของท่าน\"\n\n"
    prompt += "ตอบเป็นภาษาไทย กระชับ เข้าใจง่ายสำหรับประชาชนทั่วไป"

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text, top_chunks

user_input = st.text_input("พิมพ์คำถามเกี่ยวกับกฎหมาย")

if user_input:
    with st.spinner("กำลังค้นหาและวิเคราะห์..."):
        answer, sources = rag_answer(user_input)

    st.write("**คำตอบ:**")
    st.write(answer)

    with st.expander("📚 แหล่งข้อมูลที่ใช้อ้างอิง"):
        for i, s in enumerate(sources):
            st.write(f"{i+1}. {s}")
