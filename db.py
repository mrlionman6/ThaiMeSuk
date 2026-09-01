"""
db.py — เลเยอร์เชื่อมต่อ PostgreSQL สำหรับ ThaiMeSuk

แทนที่การอ่าน/เขียน knowledge_base.json และ low_confidence_log.json ด้วยเดิม
วาง require: sqlalchemy, psycopg2-binary, pgvector ใน requirements.txt

รองรับ vector search ผ่าน pgvector extension — ให้ PostgreSQL คำนวณ cosine distance
เองผ่าน SQL แทนการโหลด embedding ทั้งหมดมาคำนวณด้วย numpy ใน Python

การใช้งานใน main.py:
    from db import (
        init_db, get_all_knowledge_base_with_ids, get_all_knowledge_base_full,
        add_knowledge_chunk, update_knowledge_chunk, delete_knowledge_chunk,
        get_chunks_missing_embeddings, set_embedding, get_vector_scores_for_all,
        get_logs, get_logs_paginated, log_low_confidence_query, approve_log, reject_log,
    )
"""

import os
import datetime
from typing import Optional

from sqlalchemy import (
    create_engine, Column, Integer, Text, DateTime, Float, String, JSON, text
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


class Log(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    query = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    retrieved_chunks = Column(JSON)
    max_score = Column(Float)
    status = Column(String, nullable=False, default="pending")


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


# ---------- Knowledge base ----------

def get_all_knowledge_base_with_ids() -> list[dict]:
    """คืนค่า [{id, content}] ทั้งหมด ไม่แบ่งหน้า เรียงตาม id
    ใช้ตอน build BM25 corpus + จับคู่ index กับผลลัพธ์ vector score"""
    with SessionLocal() as session:
        rows = session.query(KnowledgeBase.id, KnowledgeBase.content).order_by(KnowledgeBase.id).all()
        return [{"id": r.id, "content": r.content} for r in rows]


def get_all_knowledge_base_full(page: int = 1, page_size: int = 10) -> dict:
    """คืนค่า id + content + created_at แบบแบ่งหน้า — ใช้แสดงในแท็บจัดการ KB
    คืนค่า {"items": [...], "total": จำนวนทั้งหมด}"""
    with SessionLocal() as session:
        q = session.query(KnowledgeBase).order_by(KnowledgeBase.id)
        total = q.count()
        rows = q.offset((page - 1) * page_size).limit(page_size).all()
        items = [
            {
                "id": r.id,
                "content": r.content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "has_embedding": r.embedding is not None,
            }
            for r in rows
        ]
        return {"items": items, "total": total}


def add_knowledge_chunk(content: str, embedding: Optional[list[float]] = None) -> int:
    """เพิ่ม chunk ใหม่ (ตอน admin approve) — คืนค่า id ที่เพิ่ง insert
    ถ้าไม่ส่ง embedding มา จะถูก backfill ให้เองตอน rebuild_index() รอบถัดไป"""
    with SessionLocal() as session:
        row = KnowledgeBase(content=content, embedding=embedding)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


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
    """ลบ chunk ทิ้ง — คืนค่า False ถ้าไม่เจอ id นี้"""
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
