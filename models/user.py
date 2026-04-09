import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(32), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    full_name = Column(String(128), nullable=True)
    password_hash = Column(String(128), nullable=False)
    role = Column(
        String(32),
        nullable=False,
        default="developer",
    )
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    department = relationship(
        "Department",
        foreign_keys=[department_id],
        back_populates="members",
        lazy="selectin",
    )

    project_memberships = relationship(
        "ProjectMember",
        back_populates="user",
        lazy="selectin",
    )

    owned_projects = relationship(
        "Project",
        back_populates="owner",
        lazy="selectin",
    )

    assigned_tickets = relationship(
        "Ticket",
        foreign_keys="[Ticket.assignee_id]",
        back_populates="assignee",
        lazy="selectin",
    )

    reported_tickets = relationship(
        "Ticket",
        foreign_keys="[Ticket.reporter_id]",
        back_populates="reporter",
        lazy="selectin",
    )

    comments = relationship(
        "Comment",
        back_populates="user",
        lazy="selectin",
    )

    time_entries = relationship(
        "TimeEntry",
        back_populates="user",
        lazy="selectin",
    )

    audit_logs = relationship(
        "AuditLog",
        back_populates="user",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"