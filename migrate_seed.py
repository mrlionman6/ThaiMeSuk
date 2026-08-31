"""
migrate_seed.py — รันครั้งเดียวหลัง deploy PostgreSQL แล้ว เพื่อย้ายข้อมูลเดิมเข้า DB

วิธีใช้ (รันบนเครื่อง local โดยตั้ง DATABASE_URL ให้ชี้ไป Railway ก่อน,
หรือรันผ่าน Railway CLI: `railway run python migrate_seed.py`):

    export DATABASE_URL="postgresql://..."   # copy จาก Railway Variables
    python migrate_seed.py

สคริปต์นี้ idempotent-ไม่เต็มร้อย — ถ้ารันซ้ำจะ insert ซ้ำ ดังนั้นรันแค่ครั้งเดียว
หรือเช็ค get_all_knowledge_base() ก่อนว่างเปล่าหรือยังก่อนรัน
"""

import json
import sys

from db import init_db, get_all_knowledge_base, add_knowledge_chunk, log_low_confidence_query

KB_JSON_PATH = "knowledge_base.json"
LOG_JSON_PATH = "low_confidence_log.json"


def migrate_knowledge_base():
    existing = get_all_knowledge_base()
    if existing:
        print(f"⚠️  knowledge_base มีข้อมูลอยู่แล้ว {len(existing)} rows — ข้ามการ seed (ป้องกันข้อมูลซ้ำ)")
        return

    try:
        with open(KB_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ ไม่พบ {KB_JSON_PATH} — ข้ามขั้นตอนนี้")
        return

    # ปรับ key ตามโครงสร้างจริงของ knowledge_base.json — ตัวอย่างนี้สมมติเป็น list ของ string
    # หรือ list ของ dict ที่มี key "content"
    count = 0
    for item in data:
        content = item["content"] if isinstance(item, dict) else item
        add_knowledge_chunk(content)
        count += 1

    print(f"✅ ย้าย knowledge_base เข้า DB สำเร็จ {count} chunks")


def migrate_logs():
    try:
        with open(LOG_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ℹ️  ไม่พบ {LOG_JSON_PATH} (ปกติถ้ายังไม่เคยมี log ต่ำกว่า threshold) — ข้าม")
        return

    count = 0
    for item in data:
        log_low_confidence_query(
            query=item.get("query", ""),
            answer=item.get("answer", ""),
            retrieved_chunks=item.get("retrieved_chunks", []),
            max_score=item.get("max_score", 0.0),
        )
        count += 1

    print(f"✅ ย้าย logs เข้า DB สำเร็จ {count} รายการ")


if __name__ == "__main__":
    print("กำลังสร้างตาราง (ถ้ายังไม่มี)...")
    init_db()

    print("กำลังย้าย knowledge_base...")
    migrate_knowledge_base()

    print("กำลังย้าย logs...")
    migrate_logs()

    print("เสร็จสิ้น 🎉")
