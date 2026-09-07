"""
db.py — เลเยอร์เชื่อมต่อ PostgreSQL สำหรับ ThaiMeSook

แทนที่การอ่าน/เขียน knowledge_base.json และ low_confidence_log.json ด้วยเดิม
วาง require: sqlalchemy, psycopg2-binary, pgvector ใน requirements.txt

รองรับ vector search ผ่าน pgvector extension — ให้ PostgreSQL คำนวณ cosine distance
เองผ่าน SQL แทนการโหลด embedding ทั้งหมดมาคำนวณด้วย numpy ใน Python

การใช้งานใน main.py:
    from db import (
        init_db, get_all_knowledge_base_with_ids, get_all_knowledge_base_full,
        get_all_knowledge_base_for_export,
        add_knowledge_chunk, update_knowledge_chunk, delete_knowledge_chunk,
        get_or_create_tag, set_tags_for_chunk, get_tags_for_chunk, get_all_tags,
        create_kb_snapshot, get_kb_snapshots, rollback_to_snapshot,
        get_chunks_missing_embeddings, set_embedding, get_vector_scores_for_all,
        get_logs, get_logs_paginated, log_low_confidence_query, approve_log, reject_log,
        create_user, get_user_by_username, get_user_by_id, update_user_password,
        update_user_nickname, delete_user, save_security_answers, get_security_answers_for_user,
        get_pending_user_requests, approve_user_request, reject_user_request,
        get_approved_users, update_user_role, block_user, unblock_user,
        create_chat_session, touch_chat_session, get_user_chats, get_chat_session,
        add_chat_message, get_chat_messages, delete_chat_session,
    )
"""

import os
import datetime
from typing import Optional

from sqlalchemy import (
    create_engine, Column, Integer, Text, DateTime, Float, String, JSON, text, ForeignKey, func
)
from sqlalchemy.orm import declarative_base, sessionmaker
from pgvector.sqlalchemy import Vector

# มิติของ embedding ต้องตรงกับโมเดลที่ใช้จริง — intfloat/multilingual-e5-large คืนค่า 1024 มิติ
EMBEDDING_DIM = 1024

# Railway ให้ DATABASE_URL แบบ "postgres://..." แต่ SQLAlchemy 2.x ต้องการ "postgresql://..."
DATABASE_URL = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"

    id = Column(Integer, primary_key=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)  # nullable เพราะ chunk เก่าอาจยังไม่มีค่า (backfill ทีหลัง)


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True, index=True)


class KnowledgeBaseTag(Base):
    """ตารางกลาง many-to-many — 1 chunk มีได้หลาย tag, 1 tag ผูกได้หลาย chunk"""
    __tablename__ = "knowledge_base_tags"

    id = Column(Integer, primary_key=True)
    chunk_id = Column(Integer, ForeignKey("knowledge_base.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)


class KbSnapshot(Base):
    """เก็บภาพรวมของ KB ทั้งหมด (เนื้อหา+embedding+tags) ณ จุดเวลาหนึ่ง — ใช้ทำ backup/rollback
    เก็บแค่ MAX_KB_SNAPSHOTS เวอร์ชันล่าสุด (rolling window) ไม่เก็บไม่จำกัดจำนวน กัน DB บวม"""
    __tablename__ = "kb_snapshots"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    label = Column(String, nullable=True)  # เหตุผล/ป้ายกำกับ เช่น "ก่อนรัน AI Agent ยุบรวม chunk"
    data = Column(JSON, nullable=False)  # {"chunks": [{"id":, "content":, "embedding":[...], "tags":[...]}, ...]}


class Log(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    query = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    retrieved_chunks = Column(JSON)
    max_score = Column(Float)
    status = Column(String, nullable=False, default="pending")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, nullable=True, unique=True, index=True)  # login identifier ใหม่ แทน email
    email = Column(String, nullable=True, unique=True, index=True)  # เก็บไว้เผื่อ backward-compat กับ user เก่า ไม่บังคับใช้แล้ว
    password_hash = Column(String, nullable=False)  # เก็บ bcrypt hash เท่านั้น ไม่เก็บ plain text
    nickname = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending | approved | rejected | blocked
    requested_role = Column(Integer, nullable=True)  # ระดับสิทธิ์ที่ user ขอตอนสมัคร (1/2/3)
    role = Column(Integer, nullable=True)  # ระดับสิทธิ์จริงที่ admin อนุมัติให้ (อาจต่างจาก requested_role)
    session_version = Column(Integer, nullable=False, default=0)  # เพิ่มขึ้นทุกครั้งที่ block/unblock — บังคับ logout session เก่าทุกที่
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)


class UserSecurityAnswer(Base):
    __tablename__ = "user_security_answers"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Integer, nullable=False)  # อ้างอิง SECURITY_QUESTIONS ใน main.py (id 1-10)
    answer_hash = Column(String, nullable=False)  # เก็บ bcrypt hash ของคำตอบ (normalize แล้ว) ไม่เก็บ plain text


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False, default="แชทใหม่")
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)  # ใช้เรียง "ล่าสุดก่อน" + ตัดสิน 10 อันล่าสุด


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)  # "user" หรือ "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)


def init_db():
    """สร้าง extension/ตาราง/คอลัมน์ที่ยังไม่มี — เรียกทุกครั้งตอน startup ของ FastAPI
    ปลอดภัยรันซ้ำได้ (idempotent) ทั้ง fresh DB และ DB ที่มีข้อมูลอยู่แล้ว"""
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

    Base.metadata.create_all(bind=engine)  # สร้างตารางที่ยังไม่มี (ไม่แตะตารางที่มีอยู่แล้ว)

    # ตาราง knowledge_base อาจมีอยู่แล้วจากก่อนเพิ่ม column embedding — ต้อง ALTER TABLE เพิ่มเอง
    # (create_all ไม่ alter ตารางเดิมที่มีอยู่แล้ว จะสร้างแค่ตารางที่ยังไม่มีเท่านั้น)
    with engine.connect() as conn:
        conn.execute(text(
            f"ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS embedding vector({EMBEDDING_DIM})"
        ))
        conn.commit()

    # ตาราง users อาจมีอยู่แล้วจากก่อนเพิ่ม column nickname (คนที่เคยสมัครทดสอบไปแล้ว) — ALTER TABLE เพิ่มเอง
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS nickname VARCHAR"))
        conn.commit()

    # บังคับ nickname ห้ามซ้ำกัน — ห่อ try/except เพราะถ้ามี nickname ซ้ำกันอยู่ก่อนแล้ว
    # (เช่น user เก่าที่สมัครไว้ตอนยังไม่บังคับ unique) การสร้าง index จะ fail แต่ไม่ควรทำให้แอป crash ทั้งระบบ
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_nickname ON users(nickname)"))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"เตือน: สร้าง unique index ให้ nickname ไม่สำเร็จ (อาจมีชื่อซ้ำอยู่ก่อนแล้ว) — {e}")

    # Migration: เปลี่ยนจาก email เป็น username + เพิ่มระบบอนุมัติ/สิทธิ์ผู้ใช้
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE users ALTER COLUMN email DROP NOT NULL"))  # เลิกบังคับ email แล้ว
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS requested_role INTEGER"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role INTEGER"))
        # grandfather: user ที่เคยสมัครไว้ก่อนมีระบบอนุมัติ (status ยังเป็น NULL) ให้ผ่านอัตโนมัติ
        # ไม่งั้นจะ login ไม่ได้ทันทีหลัง deploy รอบนี้ทั้งที่เคยใช้งานได้ปกติมาก่อน
        conn.execute(text("UPDATE users SET status = 'approved' WHERE status IS NULL"))
        conn.execute(text("UPDATE users SET role = 3 WHERE role IS NULL AND status = 'approved'"))
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0"))
        conn.commit()

    # กัน insert tag ซ้ำคู่เดียวกันสองรอบ (เช่น เผลอกด set_tags_for_chunk ซ้อนกัน) — เป็นตารางใหม่ create_all
    # สร้างให้แล้ว แค่เพิ่ม unique constraint คู่ (chunk_id, tag_id) เข้าไปอีกชั้น
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_tags_unique ON knowledge_base_tags(chunk_id, tag_id)"
        ))
        conn.commit()


# ---------- Knowledge base ----------

def get_all_knowledge_base_with_ids() -> list[dict]:
    """คืนค่า [{id, content}] ทั้งหมด ไม่แบ่งหน้า เรียงตาม id
    ใช้ตอน build BM25 corpus + จับคู่ index กับผลลัพธ์ vector score"""
    with SessionLocal() as session:
        rows = session.query(KnowledgeBase.id, KnowledgeBase.content).order_by(KnowledgeBase.id).all()
        return [{"id": r.id, "content": r.content} for r in rows]


def get_all_knowledge_base_full(page: int = 1, page_size: int = 10, tag_ids: Optional[list[int]] = None) -> dict:
    """คืนค่า id + content + created_at + tags แบบแบ่งหน้า — ใช้แสดงในแท็บจัดการ KB
    ถ้าส่ง tag_ids มา จะกรองเฉพาะ chunk ที่มีอย่างน้อย 1 ใน tag ที่ระบุ (OR ไม่ใช่ AND)
    คืนค่า {"items": [...], "total": จำนวนทั้งหมด}"""
    with SessionLocal() as session:
        q = session.query(KnowledgeBase)
        if tag_ids:
            q = (
                q.join(KnowledgeBaseTag, KnowledgeBaseTag.chunk_id == KnowledgeBase.id)
                .filter(KnowledgeBaseTag.tag_id.in_(tag_ids))
                .distinct()
            )
        q = q.order_by(KnowledgeBase.id)
        total = q.count()
        rows = q.offset((page - 1) * page_size).limit(page_size).all()
        items = [
            {
                "id": r.id,
                "content": r.content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "has_embedding": r.embedding is not None,
                "tags": get_tags_for_chunk(r.id),
            }
            for r in rows
        ]
        return {"items": items, "total": total}


def get_all_knowledge_base_for_export(tag_ids: Optional[list[int]] = None) -> list[dict]:
    """เหมือน get_all_knowledge_base_full แต่ไม่แบ่งหน้า — เอาทั้งหมด (หรือทั้งหมดที่ตรง filter) สำหรับ export"""
    with SessionLocal() as session:
        q = session.query(KnowledgeBase)
        if tag_ids:
            q = (
                q.join(KnowledgeBaseTag, KnowledgeBaseTag.chunk_id == KnowledgeBase.id)
                .filter(KnowledgeBaseTag.tag_id.in_(tag_ids))
                .distinct()
            )
        rows = q.order_by(KnowledgeBase.id).all()
        return [
            {"id": r.id, "content": r.content, "tags": get_tags_for_chunk(r.id)}
            for r in rows
        ]


# ---------- Tags (many-to-many กับ knowledge_base) ----------

def get_or_create_tag(name: str) -> int:
    """คืน tag id — ถ้ายังไม่มี tag ชื่อนี้ (เทียบแบบ trim ช่องว่างแล้ว) จะสร้างใหม่ให้อัตโนมัติ"""
    name = name.strip()
    with SessionLocal() as session:
        existing = session.query(Tag).filter(Tag.name == name).first()
        if existing:
            return existing.id
        row = Tag(name=name)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def set_tags_for_chunk(chunk_id: int, tag_names: list[str]):
    """ตั้ง tag ให้ chunk หนึ่ง — แทนที่ชุดเดิมทั้งหมดด้วยชุดใหม่ที่ส่งมา (ไม่ใช่ append ต่อท้าย)
    ส่ง list ว่างมาเพื่อลบ tag ทั้งหมดออกจาก chunk นี้ได้"""
    with SessionLocal() as session:
        session.query(KnowledgeBaseTag).filter(KnowledgeBaseTag.chunk_id == chunk_id).delete()
        session.commit()

    seen = set()
    for name in tag_names:
        name = name.strip()
        if not name or name in seen:
            continue  # กัน tag ซ้ำในลิสต์เดียวกัน (เช่น user พิมพ์ "ภาษี, ภาษี")
        seen.add(name)
        tag_id = get_or_create_tag(name)
        with SessionLocal() as session:
            session.add(KnowledgeBaseTag(chunk_id=chunk_id, tag_id=tag_id))
            session.commit()


def get_tags_for_chunk(chunk_id: int) -> list[str]:
    with SessionLocal() as session:
        rows = (
            session.query(Tag.name)
            .join(KnowledgeBaseTag, KnowledgeBaseTag.tag_id == Tag.id)
            .filter(KnowledgeBaseTag.chunk_id == chunk_id)
            .order_by(Tag.name)
            .all()
        )
        return [r[0] for r in rows]


def get_all_tags() -> list[dict]:
    """คืน tag ทั้งหมดพร้อมจำนวน chunk ที่ผูกอยู่ — ใช้ทำ dropdown ตัวกรองในหน้า admin"""
    with SessionLocal() as session:
        rows = (
            session.query(Tag.id, Tag.name, func.count(KnowledgeBaseTag.chunk_id))
            .outerjoin(KnowledgeBaseTag, KnowledgeBaseTag.tag_id == Tag.id)
            .group_by(Tag.id, Tag.name)
            .order_by(Tag.name)
            .all()
        )
        return [{"id": r[0], "name": r[1], "count": r[2]} for r in rows]


def rename_tag(tag_id: int, new_name: str) -> bool:
    """เปลี่ยนชื่อ tag — คืน False ถ้าไม่เจอ id หรือชื่อใหม่ซ้ำกับ tag อื่นที่มีอยู่แล้ว"""
    new_name = new_name.strip()
    with SessionLocal() as session:
        row = session.get(Tag, tag_id)
        if row is None:
            return False
        existing = session.query(Tag).filter(Tag.name == new_name, Tag.id != tag_id).first()
        if existing:
            return False  # ชื่อซ้ำกับ tag อื่น
        row.name = new_name
        session.commit()
        return True


def delete_tag_entirely(tag_id: int) -> bool:
    """ลบ tag ออกจากทุก chunk ที่ผูกอยู่ทั้งหมด + ลบตัว tag เอง
    (ON DELETE CASCADE ลบแถวใน knowledge_base_tags ที่เกี่ยวข้องให้อัตโนมัติ)"""
    with SessionLocal() as session:
        row = session.get(Tag, tag_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def remove_tag_from_chunk_range(tag_id: int, start_id: int, end_id: int) -> int:
    """ลบ tag ออกจาก chunk เฉพาะที่ id อยู่ในช่วง [start_id, end_id] เท่านั้น (ไม่ลบตัว tag เอง)
    คืนค่าจำนวนแถวที่ถูกลบจริง"""
    with SessionLocal() as session:
        rows = (
            session.query(KnowledgeBaseTag)
            .filter(
                KnowledgeBaseTag.tag_id == tag_id,
                KnowledgeBaseTag.chunk_id >= start_id,
                KnowledgeBaseTag.chunk_id <= end_id,
            )
            .all()
        )
        count = len(rows)
        for r in rows:
            session.delete(r)
        session.commit()
        return count


def add_tag_to_chunk_range(tag_name: str, start_id: int, end_id: int) -> int:
    """เพิ่ม tag ให้ chunk ทุกตัวที่ id อยู่ในช่วง [start_id, end_id] (สร้าง tag ใหม่อัตโนมัติถ้ายังไม่มี)
    ข้าม chunk ที่มี tag นี้ผูกอยู่แล้ว (กันซ้ำ) — คืนค่าจำนวน chunk ที่เพิ่มจริง"""
    tag_id = get_or_create_tag(tag_name)
    with SessionLocal() as session:
        chunk_ids = [
            r.id for r in session.query(KnowledgeBase.id)
            .filter(KnowledgeBase.id >= start_id, KnowledgeBase.id <= end_id)
            .all()
        ]
    added = 0
    for chunk_id in chunk_ids:
        with SessionLocal() as session:
            existing = session.query(KnowledgeBaseTag).filter(
                KnowledgeBaseTag.chunk_id == chunk_id, KnowledgeBaseTag.tag_id == tag_id
            ).first()
            if not existing:
                session.add(KnowledgeBaseTag(chunk_id=chunk_id, tag_id=tag_id))
                session.commit()
                added += 1
    return added


def get_chunk_id_range() -> dict:
    """คืนค่า id ต่ำสุด/สูงสุดปัจจุบันของ knowledge_base — ใช้ทำ placeholder/validation ใน UI ตอนกรอกช่วง id"""
    with SessionLocal() as session:
        result = session.query(func.min(KnowledgeBase.id), func.max(KnowledgeBase.id)).first()
        return {"min_id": result[0], "max_id": result[1]}


def count_knowledge_base_by_scope(
    tag_ids: Optional[list[int]] = None,
    untagged: bool = False,
    start_id: Optional[int] = None,
    end_id: Optional[int] = None,
) -> int:
    """นับจำนวน chunk ที่ตรงกับเงื่อนไข scope ที่ระบุ — ใช้ทำ live preview ตอนตั้งค่า filter
    ก่อนสั่งงานจริง (ทั้งงาน bulk tag ธรรมดาตอนนี้ และงาน agent ในระยะถัดไป)"""
    with SessionLocal() as session:
        q = session.query(KnowledgeBase.id)
        if start_id is not None:
            q = q.filter(KnowledgeBase.id >= start_id)
        if end_id is not None:
            q = q.filter(KnowledgeBase.id <= end_id)
        if untagged:
            q = (
                q.outerjoin(KnowledgeBaseTag, KnowledgeBaseTag.chunk_id == KnowledgeBase.id)
                .filter(KnowledgeBaseTag.id.is_(None))
            )
        elif tag_ids:
            q = (
                q.join(KnowledgeBaseTag, KnowledgeBaseTag.chunk_id == KnowledgeBase.id)
                .filter(KnowledgeBaseTag.tag_id.in_(tag_ids))
                .distinct()
            )
        return q.count()


# ---------- Backup / Rollback (kb_snapshots) ----------
MAX_KB_SNAPSHOTS = 2  # เก็บแค่เวอร์ชันล่าสุด N อัน (rolling window) ตามที่ตกลงกันไว้ — ลบเก่าสุดทิ้งอัตโนมัติถ้าเกิน


def create_kb_snapshot(label: str = "") -> int:
    """ถ่ายภาพ KB ทั้งหมด (เนื้อหา+embedding+tags) ณ ตอนนี้เก็บไว้เป็น snapshot ใหม่
    เก็บแค่ MAX_KB_SNAPSHOTS เวอร์ชันล่าสุด คืนค่า snapshot id ที่เพิ่งสร้าง"""
    with SessionLocal() as session:
        chunks = session.query(KnowledgeBase).order_by(KnowledgeBase.id).all()
        chunk_data = []
        for c in chunks:
            tags = get_tags_for_chunk(c.id)
            embedding_list = list(c.embedding) if c.embedding is not None else None
            chunk_data.append({"id": c.id, "content": c.content, "embedding": embedding_list, "tags": tags})

        snapshot = KbSnapshot(label=label, data={"chunks": chunk_data})
        session.add(snapshot)
        session.commit()
        session.refresh(snapshot)
        new_id = snapshot.id

        # ลบเก่าสุดทิ้งถ้าเกิน MAX_KB_SNAPSHOTS (rolling window)
        all_snapshots = session.query(KbSnapshot).order_by(KbSnapshot.created_at.desc()).all()
        if len(all_snapshots) > MAX_KB_SNAPSHOTS:
            for old in all_snapshots[MAX_KB_SNAPSHOTS:]:
                session.delete(old)
            session.commit()

        return new_id


def get_kb_snapshots() -> list[dict]:
    """คืนรายการ snapshot ทั้งหมด (แค่ metadata ไม่ส่งข้อมูลเต็มกลับ กันโหลดหนัก) เรียงใหม่สุดก่อน"""
    with SessionLocal() as session:
        rows = session.query(KbSnapshot).order_by(KbSnapshot.created_at.desc()).all()
        return [
            {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "label": r.label,
                "chunk_count": len(r.data.get("chunks", [])) if r.data else 0,
            }
            for r in rows
        ]


def rollback_to_snapshot(snapshot_id: int) -> bool:
    """ล้าง KB ปัจจุบันทั้งหมด แล้ว restore กลับไปเป็นเวอร์ชันใน snapshot ที่ระบุ (คืน id เดิมเป๊ะทุกตัว)
    คืนค่า False ถ้าไม่พบ snapshot นี้ — caller ควรสร้าง snapshot ของสถานะปัจจุบันไว้ก่อนเรียกฟังก์ชันนี้เสมอ
    (เผื่ออยาก 'ย้อนกลับการ rollback' ได้อีกที ถ้า rollback ผิดเวอร์ชัน)"""
    with SessionLocal() as session:
        snapshot = session.get(KbSnapshot, snapshot_id)
        if snapshot is None:
            return False
        chunks_data = snapshot.data.get("chunks", [])

    # ขั้น 1: ลบข้อมูลปัจจุบันทั้งหมด (tags ถูกลบตาม CASCADE เมื่อลบ knowledge_base rows)
    with SessionLocal() as session:
        session.query(KnowledgeBaseTag).delete()
        session.query(KnowledgeBase).delete()
        session.commit()

    # ขั้น 2: restore เนื้อหา+embedding กลับเข้าไปตรง id เดิมเป๊ะ
    with SessionLocal() as session:
        for c in chunks_data:
            session.add(KnowledgeBase(id=c["id"], content=c["content"], embedding=c.get("embedding")))
        session.commit()

    # ขั้น 3: เตรียม tag ทั้งหมดที่ต้องใช้ก่อน (get_or_create_tag มี session ของตัวเอง เรียกแยกนอก session หลักปลอดภัยกว่า)
    tag_name_to_id = {}
    for c in chunks_data:
        for tag_name in c.get("tags") or []:
            if tag_name not in tag_name_to_id:
                tag_name_to_id[tag_name] = get_or_create_tag(tag_name)

    # ขั้น 4: ผูก tag กลับเข้า chunk ตามเดิม
    with SessionLocal() as session:
        for c in chunks_data:
            for tag_name in c.get("tags") or []:
                session.add(KnowledgeBaseTag(chunk_id=c["id"], tag_id=tag_name_to_id[tag_name]))
        session.commit()

    # ขั้น 5: sync sequence กัน id ชนกับ auto-increment รอบถัดไป
    with engine.connect() as conn:
        conn.execute(text(
            "SELECT setval(pg_get_serial_sequence('knowledge_base', 'id'), "
            "GREATEST((SELECT MAX(id) FROM knowledge_base), 1))"
        ))
        conn.commit()

    return True


def add_knowledge_chunk(content: str, embedding: Optional[list[float]] = None) -> int:
    """เพิ่ม chunk ใหม่ (ตอน admin approve) — คืนค่า id ที่เพิ่ง insert
    ถ้าไม่ส่ง embedding มา จะถูก backfill ให้เองตอน rebuild_index() รอบถัดไป"""
    with SessionLocal() as session:
        row = KnowledgeBase(content=content, embedding=embedding)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def knowledge_chunk_exists(chunk_id: int) -> bool:
    """เช็คว่ามี chunk ที่ id นี้อยู่แล้วหรือยัง — ใช้เช็คก่อน insert แบบระบุตำแหน่งเอง กันเผลอ insert ทับของเดิม"""
    with SessionLocal() as session:
        return session.get(KnowledgeBase, chunk_id) is not None


def add_knowledge_chunk_at_id(chunk_id: int, content: str, embedding: Optional[list[float]] = None) -> bool:
    """เพิ่ม chunk ใหม่ที่ id ที่ระบุตรงๆ (ใช้ตอนอยากเติมคืนตำแหน่งที่เคยลบไปโดยไม่ตั้งใจ)
    คืนค่า False ถ้า id นี้มีอยู่แล้ว (caller ควรเช็ค knowledge_chunk_exists() ก่อนเรียกอยู่แล้ว แต่กันซ้ำอีกชั้น)
    หลัง insert จะ sync ตัวนับ sequence ให้ id ถัดไปที่ auto-increment (ไม่ระบุ id เอง) ไม่ชนกับที่เพิ่งใส่มือไปตรงนี้"""
    with SessionLocal() as session:
        existing = session.get(KnowledgeBase, chunk_id)
        if existing is not None:
            return False
        row = KnowledgeBase(id=chunk_id, content=content, embedding=embedding)
        session.add(row)
        session.commit()

    # sync sequence โดยใช้ pg_get_serial_sequence() แทนเดาชื่อ sequence เอง (ปลอดภัยกว่า)
    with engine.connect() as conn:
        conn.execute(text(
            "SELECT setval(pg_get_serial_sequence('knowledge_base', 'id'), "
            "GREATEST((SELECT MAX(id) FROM knowledge_base), 1))"
        ))
        conn.commit()
    return True


def update_knowledge_chunk(chunk_id: int, content: str, embedding: Optional[list[float]] = None) -> bool:
    """แก้ไขเนื้อหา chunk ที่มีอยู่แล้ว — คืนค่า False ถ้าไม่เจอ id นี้
    ถ้าส่ง embedding มาด้วย จะอัปเดตพร้อมกัน (ควรส่งเสมอเมื่อ content เปลี่ยน เพราะ embedding เดิมจะไม่ตรงกับเนื้อหาใหม่แล้ว)"""
    with SessionLocal() as session:
        row = session.get(KnowledgeBase, chunk_id)
        if row is None:
            return False
        row.content = content
        if embedding is not None:
            row.embedding = embedding
        session.commit()
        return True


def delete_knowledge_chunk(chunk_id: int) -> bool:
    """ลบ chunk ทิ้ง — คืนค่า False ถ้าไม่เจอ id นี้ (ON DELETE CASCADE ลบ tag ที่ผูกไว้ให้เองด้วย)"""
    with SessionLocal() as session:
        row = session.get(KnowledgeBase, chunk_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def get_chunks_missing_embeddings() -> list[dict]:
    """คืนค่า [{id, content}] ของ chunk ที่ยังไม่มี embedding (เช่น chunk เก่าก่อนเพิ่มฟีเจอร์นี้)
    ใช้ backfill ตอน startup"""
    with SessionLocal() as session:
        rows = (
            session.query(KnowledgeBase.id, KnowledgeBase.content)
            .filter(KnowledgeBase.embedding.is_(None))
            .all()
        )
        return [{"id": r.id, "content": r.content} for r in rows]


def set_embedding(chunk_id: int, embedding: list[float]) -> bool:
    """ตั้งค่า embedding ให้ chunk ที่มีอยู่แล้ว (ใช้ตอน backfill) — คืนค่า False ถ้าไม่เจอ id นี้"""
    with SessionLocal() as session:
        row = session.get(KnowledgeBase, chunk_id)
        if row is None:
            return False
        row.embedding = embedding
        session.commit()
        return True


def get_vector_scores_for_all(query_embedding: list[float]) -> dict[int, float]:
    """หัวใจของ vector search ผ่าน pgvector — ให้ PostgreSQL คำนวณ cosine distance เองทั้งหมด
    ผ่าน SQL (ไม่ใช่ python loop / numpy) แล้วคืนค่า similarity (1 - distance) เป็น dict {id: similarity}
    ยิ่งค่าใกล้ 1 ยิ่งเหมือน query มากที่สุด, chunk ที่ยังไม่มี embedding จะถูกข้ามไป (ไม่รวมใน dict)"""
    with SessionLocal() as session:
        rows = (
            session.query(
                KnowledgeBase.id,
                KnowledgeBase.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .filter(KnowledgeBase.embedding.isnot(None))
            .all()
        )
        return {r.id: 1 - r.distance for r in rows}


# ---------- Users & Auth ----------
# หมายเหตุ: การ hash/verify password (bcrypt) ทำที่ main.py ไม่ใช่ที่นี่
# เพราะเป็นเรื่อง auth logic ไม่ใช่ data access — db.py รับแค่ password_hash ที่ hash มาแล้ว

def create_user(username: str, password_hash: str, nickname: str, requested_role: int):
    """สร้างคำขอสมัครสมาชิกใหม่ — status เริ่มต้นเป็น 'pending' เสมอ ต้องรอ admin อนุมัติก่อนถึง login ได้
    คืนค่า user id (int) ถ้าสำเร็จ, หรือ 'username_taken' / 'nickname_taken' (str) ถ้าซ้ำกับที่มีอยู่แล้ว"""
    with SessionLocal() as session:
        if session.query(User).filter(User.username == username).first():
            return "username_taken"
        if session.query(User).filter(User.nickname == nickname).first():
            return "nickname_taken"
        row = User(
            username=username,
            password_hash=password_hash,
            nickname=nickname,
            requested_role=requested_role,
            status="pending",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def get_user_by_username(username: str) -> Optional[dict]:
    """ใช้ตอน login/ลืมรหัสผ่าน — คืน password_hash มาด้วยเพื่อให้ main.py เอาไป verify"""
    with SessionLocal() as session:
        row = session.query(User).filter(User.username == username).first()
        if row is None:
            return None
        return {
            "id": row.id,
            "username": row.username,
            "password_hash": row.password_hash,
            "nickname": row.nickname,
            "status": row.status,
            "role": row.role,
            "session_version": row.session_version,
        }


def get_user_by_id(user_id: int) -> Optional[dict]:
    """ใช้เช็คตอนโหลดหน้า (GET /api/auth/me) และเช็คทุก request ที่ต้อง login — ไม่คืน password_hash ออกไป"""
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "username": row.username,
            "nickname": row.nickname,
            "status": row.status,
            "role": row.role,
            "session_version": row.session_version,
        }


def update_user_password(user_id: int, new_password_hash: str) -> bool:
    """ใช้ทั้งตอนเปลี่ยนรหัสผ่านปกติ (login อยู่) และตอนตั้งรหัสผ่านใหม่ผ่าน security questions"""
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None:
            return False
        row.password_hash = new_password_hash
        session.commit()
        return True


# ---------- Admin: อนุมัติคำขอสมัครสมาชิก + จัดการสิทธิ์ ----------

def get_pending_user_requests(page: int = 1, page_size: int = 10) -> dict:
    """คำขอสมัครที่ยังไม่ได้ตัดสินใจ (status='pending') — ใช้แสดงในแท็บ 'คำขอสมัครสมาชิก'"""
    with SessionLocal() as session:
        q = session.query(User).filter(User.status == "pending").order_by(User.created_at.desc())
        total = q.count()
        rows = q.offset((page - 1) * page_size).limit(page_size).all()
        items = [
            {
                "id": r.id,
                "username": r.username,
                "nickname": r.nickname,
                "requested_role": r.requested_role,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
        return {"items": items, "total": total}


def approve_user_request(user_id: int, granted_role: int) -> bool:
    """อนุมัติคำขอ — ตั้ง status เป็น approved พร้อมให้สิทธิ์จริง (อาจต่างจาก requested_role ที่ user ขอมาได้)"""
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None or row.status != "pending":
            return False
        row.status = "approved"
        row.role = granted_role
        session.commit()
        return True


def reject_user_request(user_id: int) -> bool:
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None or row.status != "pending":
            return False
        row.status = "rejected"
        session.commit()
        return True


def get_approved_users(page: int = 1, page_size: int = 10) -> dict:
    """บัญชีที่ผ่านการอนุมัติแล้วทั้งหมด (รวมที่ถูก block ไว้ด้วย) — ใช้แสดงในแท็บ 'จัดการบัญชี'
    บัญชี pending/rejected ไม่แสดงในนี้ (อยู่แท็บ 'คำขอสมัครสมาชิก' แทน)"""
    with SessionLocal() as session:
        q = (
            session.query(User)
            .filter(User.status.in_(["approved", "blocked"]))
            .order_by(User.created_at.desc())
        )
        total = q.count()
        rows = q.offset((page - 1) * page_size).limit(page_size).all()
        items = [
            {
                "id": r.id,
                "username": r.username,
                "nickname": r.nickname,
                "role": r.role,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
        return {"items": items, "total": total}


def block_user(user_id: int) -> bool:
    """ระงับการใช้งานชั่วคราว (เช่นระหว่างสงสัยว่าโดน hack) — เพิ่ม session_version บังคับ logout
    session เดิมทุกที่ทันที คืนค่า False ถ้าไม่เจอหรือสถานะไม่ใช่ approved"""
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None or row.status != "approved":
            return False
        row.status = "blocked"
        row.session_version = (row.session_version or 0) + 1
        session.commit()
        return True


def unblock_user(user_id: int) -> bool:
    """ปลด block กลับมาใช้งานได้ปกติ — เพิ่ม session_version ด้วยเช่นกัน (กันกรณีมี session ค้างช่วง block)
    คืนค่า False ถ้าไม่เจอหรือสถานะไม่ใช่ blocked"""
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None or row.status != "blocked":
            return False
        row.status = "approved"
        row.session_version = (row.session_version or 0) + 1
        session.commit()
        return True


def update_user_role(user_id: int, role: int) -> bool:
    """admin เปลี่ยนระดับสิทธิ์ของ user คนหนึ่งทีหลังได้ (ผ่านแท็บ 'จัดการบัญชี')"""
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None:
            return False
        row.role = role
        session.commit()
        return True


def update_user_nickname(user_id: int, nickname: str) -> str:
    """คืนค่า 'ok' สำเร็จ, 'not_found' ไม่เจอ user, 'nickname_taken' ถ้าชื่อนี้มีคนอื่นใช้อยู่แล้ว"""
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None:
            return "not_found"
        conflict = (
            session.query(User)
            .filter(User.nickname == nickname, User.id != user_id)
            .first()
        )
        if conflict:
            return "nickname_taken"
        row.nickname = nickname
        session.commit()
        return "ok"


def delete_user(user_id: int) -> bool:
    """ลบบัญชีถาวร — ON DELETE CASCADE ลบ chat_sessions (+ chat_messages ที่ผูกอยู่)
    และ user_security_answers ที่เกี่ยวข้องทั้งหมดให้เองที่ระดับ DB"""
    with SessionLocal() as session:
        row = session.get(User, user_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


# ---------- Security questions (สำหรับลืมรหัสผ่าน — ไม่ใช้อีเมล) ----------

def save_security_answers(user_id: int, answers: list[dict]):
    """answers: [{"question_id": int, "answer_hash": str}, ...] — เรียกครั้งเดียวตอนสมัคร"""
    with SessionLocal() as session:
        for a in answers:
            row = UserSecurityAnswer(
                user_id=user_id,
                question_id=a["question_id"],
                answer_hash=a["answer_hash"],
            )
            session.add(row)
        session.commit()


def get_security_answers_for_user(user_id: int) -> list[dict]:
    """คืน question_id + answer_hash ทั้งหมดที่ user คนนี้เคยตั้งไว้ (5 ข้อ)"""
    with SessionLocal() as session:
        rows = session.query(UserSecurityAnswer).filter(UserSecurityAnswer.user_id == user_id).all()
        return [{"question_id": r.question_id, "answer_hash": r.answer_hash} for r in rows]


# ---------- Chat sessions & messages ----------
MAX_CHATS_PER_USER = 10  # เก็บแค่ 10 แชทล่าสุดต่อบัญชี เกินนี้ลบตัวเก่าสุดทิ้งอัตโนมัติ


def _enforce_chat_limit(user_id: int, max_chats: int = MAX_CHATS_PER_USER):
    """ลบแชทเก่าสุดทิ้งถ้าเกิน max_chats — เรียกทุกครั้งหลังสร้างแชทใหม่
    ลบผ่าน ORM (ไม่ใช่ raw SQL) เพื่อให้ ON DELETE CASCADE ที่ตั้งไว้ใน ForeignKey ลบ
    chat_messages ที่เกี่ยวข้องให้เองที่ระดับ DB ไม่ต้องวนลบ message เองใน Python"""
    with SessionLocal() as session:
        rows = (
            session.query(ChatSession)
            .filter(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .all()
        )
        if len(rows) > max_chats:
            for row in rows[max_chats:]:
                session.delete(row)
            session.commit()


def create_chat_session(user_id: int, title: str = "แชทใหม่") -> int:
    with SessionLocal() as session:
        row = ChatSession(user_id=user_id, title=title)
        session.add(row)
        session.commit()
        session.refresh(row)
        new_id = row.id

    _enforce_chat_limit(user_id)
    return new_id


def touch_chat_session(session_id: int):
    """อัปเดต updated_at ตอนมีข้อความใหม่เข้าแชท — ใช้เรียงลำดับ 'ล่าสุดก่อน' ในไซด์บาร์"""
    with SessionLocal() as session:
        row = session.get(ChatSession, session_id)
        if row is not None:
            row.updated_at = datetime.datetime.utcnow()
            session.commit()


def get_user_chats(user_id: int) -> list[dict]:
    """คืนรายการแชทของ user เรียงล่าสุดก่อน — ใช้แสดงในไซด์บาร์"""
    with SessionLocal() as session:
        rows = (
            session.query(ChatSession)
            .filter(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .all()
        )
        return [
            {"id": r.id, "title": r.title, "updated_at": r.updated_at.isoformat() if r.updated_at else None}
            for r in rows
        ]


def get_chat_session(session_id: int, user_id: int) -> Optional[dict]:
    """คืนค่า None ถ้าไม่เจอ หรือแชทนี้ไม่ใช่ของ user คนนี้ (กัน user คนอื่นแอบดู/แก้แชทของคนอื่น)"""
    with SessionLocal() as session:
        row = (
            session.query(ChatSession)
            .filter(ChatSession.id == session_id, ChatSession.user_id == user_id)
            .first()
        )
        if row is None:
            return None
        return {"id": row.id, "title": row.title}


def add_chat_message(session_id: int, role: str, content: str) -> int:
    with SessionLocal() as session:
        row = ChatMessage(session_id=session_id, role=role, content=content)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def get_chat_messages(session_id: int) -> list[dict]:
    """คืนข้อความทั้งหมดในแชทเดียว เรียงตามเวลา — ไม่เช็ค ownership ในนี้ (caller ต้องเช็คผ่าน get_chat_session ก่อนเสมอ)"""
    with SessionLocal() as session:
        rows = (
            session.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
            .all()
        )
        return [
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def delete_chat_session(session_id: int, user_id: int) -> bool:
    """ลบแชท — คืนค่า False ถ้าไม่เจอหรือไม่ใช่เจ้าของ ON DELETE CASCADE ลบ message ที่เกี่ยวข้องให้เอง"""
    with SessionLocal() as session:
        row = (
            session.query(ChatSession)
            .filter(ChatSession.id == session_id, ChatSession.user_id == user_id)
            .first()
        )
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


# ---------- Logs ----------

def log_low_confidence_query(
    query: str, answer: str, retrieved_chunks: list, max_score: float
) -> int:
    """บันทึกคำถามที่ confidence ต่ำ (status เริ่มต้น = pending)"""
    with SessionLocal() as session:
        row = Log(
            query=query,
            answer=answer,
            retrieved_chunks=retrieved_chunks,
            max_score=max_score,
            status="pending",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def get_logs(status: Optional[str] = None) -> list[dict]:
    """ดึง logs ทั้งหมด (ไม่แบ่งหน้า) หรือกรองตาม status — ใช้ lookup ภายใน (เช่นตอน approve หา log ด้วย id)"""
    with SessionLocal() as session:
        q = session.query(Log)
        if status:
            q = q.filter(Log.status == status)
        rows = q.order_by(Log.timestamp.desc()).all()
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "query": r.query,
                "answer": r.answer,
                "retrieved_chunks": r.retrieved_chunks,
                "max_score": r.max_score,
                "status": r.status,
            }
            for r in rows
        ]


def get_logs_paginated(status: Optional[str] = None, page: int = 1, page_size: int = 10) -> dict:
    """ดึง logs แบบแบ่งหน้า — ใช้แสดงในแท็บ 'รอตรวจสอบ'
    คืนค่า {"items": [...], "total": จำนวนทั้งหมด}"""
    with SessionLocal() as session:
        q = session.query(Log)
        if status:
            q = q.filter(Log.status == status)
        total = q.count()
        rows = q.order_by(Log.timestamp.desc()).offset((page - 1) * page_size).limit(page_size).all()
        items = [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "query": r.query,
                "answer": r.answer,
                "retrieved_chunks": r.retrieved_chunks,
                "max_score": r.max_score,
                "status": r.status,
            }
            for r in rows
        ]
        return {"items": items, "total": total}


def approve_log(log_id: int) -> bool:
    """เปลี่ยน status เป็น approved — เรียกคู่กับ add_knowledge_chunk() ใน endpoint เดิม"""
    with SessionLocal() as session:
        row = session.get(Log, log_id)
        if row is None:
            return False
        row.status = "approved"
        session.commit()
        return True


def reject_log(log_id: int) -> bool:
    """เปลี่ยน status เป็น rejected"""
    with SessionLocal() as session:
        row = session.get(Log, log_id)
        if row is None:
            return False
        row.status = "rejected"
        session.commit()
        return True
