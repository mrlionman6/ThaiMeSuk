import streamlit as st
import anthropic

st.title("🇹🇭 ผู้ช่วยข้อมูลนำเข้า-ส่งออกไทย")
st.write("ทดสอบเชื่อมต่อ Claude API")

# รับ API Key จากผู้ใช้ (ชั่วคราวสำหรับทดสอบ)
api_key = st.text_input("ใส่ Anthropic API Key", type="password")

if api_key:
    client = anthropic.Anthropic(api_key=api_key)
    
    user_input = st.text_input("ลองพิมพ์คำถามดู เช่น 'สวัสดี'")
    
    if user_input:
        with st.spinner("กำลังคิด..."):
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[
                    {"role": "user", "content": user_input}
                ]
            )
            st.write("**คำตอบ:**")
            st.write(response.content[0].text)
