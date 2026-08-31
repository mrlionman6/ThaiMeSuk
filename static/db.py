"""
db.py — เลเยอร์เชื่อมต่อ PostgreSQL สำหรับ ThaiMeSuk

แทนที่การอ่าน/เขียน knowledge_base.json และ low_confidence_log.json ด้วยเดิม
วาง require: sqlalchemy, psycopg2-binary ใน requirements.txt (ดู requirements_addition.txt)

การใช้งานใน main.py:
    from db import (
        init_db, get_all_knowledge_base, add_knowledge_chunk,
        get_logs, log_low_confidence_query, approve_log, reject_log,
    )
"""

import os
import datetime
from typing import Optional

from sqlalchemy import (
    create_engine, Column, Integer, Text, DateTime, Float, String, JSON
)
from sqlalchemy.orm import declarative_base, sessionmaker

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
    """สร้างตารางถ้ายังไม่มี — เรียกครั้งเดียวตอน startup ของ FastAPI"""
    Base.metadata.create_all(bind=engine)


# ---------- Knowledge base ----------

def get_all_knowledge_base() -> list[str]:
    """คืนค่า list ของ content ทั้งหมด เรียงตาม id — ใช้ตอน build/rebuild index"""
    with SessionLocal() as session:
        rows = session.query(KnowledgeBase).order_by(KnowledgeBase.id).all()
        return [row.content for row in rows]


def add_knowledge_chunk(content: str) -> int:
    """เพิ่ม chunk ใหม่ (ตอน admin approve) — คืนค่า id ที่เพิ่ง insert"""
    with SessionLocal() as session:
        row = KnowledgeBase(content=content)
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


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
    """ดึง logs ทั้งหมด หรือกรองตาม status (เช่น 'pending') — ใช้แสดงในหน้า admin"""
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
