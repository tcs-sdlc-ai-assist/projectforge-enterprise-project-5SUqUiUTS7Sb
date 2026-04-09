import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    action = Column(String(64), nullable=False)
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(String(36), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", foreign_keys=[actor_id], lazy="selectin")

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action={self.action}, entity_type={self.entity_type}, entity_id={self.entity_id})>"