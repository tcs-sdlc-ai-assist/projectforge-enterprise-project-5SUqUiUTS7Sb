import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base

if TYPE_CHECKING:
    from models.user import User


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    code = Column(String(10), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    head_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    head: Optional["User"] = relationship(
        "User",
        foreign_keys=[head_id],
        lazy="selectin",
    )

    members: List["User"] = relationship(
        "User",
        back_populates="department",
        foreign_keys="User.department_id",
        lazy="selectin",
    )

    @property
    def member_count(self) -> int:
        if self.members is None:
            return 0
        return len(self.members)

    def __repr__(self) -> str:
        return f"<Department(id={self.id}, name='{self.name}', code='{self.code}')>"