import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from database import Base

ticket_labels = Table(
    "ticket_labels",
    Base.metadata,
    Column("ticket_id", Integer, ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
    Column("label_id", Integer, ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True),
)


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    sprint_id = Column(Integer, ForeignKey("sprints.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_id = Column(Integer, ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True, index=True)
    ticket_key = Column(String(32), unique=True, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(
        Enum("backlog", "todo", "in_progress", "in_review", "done", "closed", name="ticket_status"),
        nullable=False,
        default="backlog",
    )
    ticket_type = Column(
        Enum("bug", "feature", "task", "improvement", name="ticket_type_enum"),
        nullable=False,
        default="task",
    )
    priority = Column(
        Enum("critical", "high", "medium", "low", name="ticket_priority"),
        nullable=False,
        default="medium",
    )
    assignee_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reporter_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=False, index=True)
    story_points = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    project = relationship(
        "Project",
        back_populates="tickets",
        lazy="selectin",
        foreign_keys=[project_id],
    )
    sprint = relationship(
        "Sprint",
        back_populates="tickets",
        lazy="selectin",
        foreign_keys=[sprint_id],
    )
    assignee = relationship(
        "User",
        back_populates="assigned_tickets",
        lazy="selectin",
        foreign_keys=[assignee_id],
    )
    reporter = relationship(
        "User",
        back_populates="reported_tickets",
        lazy="selectin",
        foreign_keys=[reporter_id],
    )
    parent = relationship(
        "Ticket",
        back_populates="subtasks",
        lazy="selectin",
        remote_side=[id],
        foreign_keys=[parent_id],
    )
    subtasks = relationship(
        "Ticket",
        back_populates="parent",
        lazy="selectin",
        foreign_keys=[parent_id],
    )
    labels = relationship(
        "Label",
        secondary=ticket_labels,
        back_populates="tickets",
        lazy="selectin",
    )
    comments = relationship(
        "Comment",
        back_populates="ticket",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    time_entries = relationship(
        "TimeEntry",
        back_populates="ticket",
        lazy="selectin",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Ticket(id={self.id}, key='{self.ticket_key}', title='{self.title}', status='{self.status}')>"

    @property
    def type(self) -> str:
        return self.ticket_type