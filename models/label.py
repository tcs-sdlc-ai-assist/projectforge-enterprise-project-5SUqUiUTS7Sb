import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, Table, func
from sqlalchemy.orm import relationship

from database import Base


ticket_labels = Table(
    "ticket_labels",
    Base.metadata,
    Column("ticket_id", Integer, ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True),
    Column("label_id", Integer, ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True),
)


class Label(Base):
    __tablename__ = "labels"

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_label_name_per_project"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(32), nullable=False)
    color = Column(String(7), nullable=False, default="#6b7280")
    created_at = Column(DateTime, nullable=False, default=func.now())

    project = relationship("Project", back_populates="labels", lazy="selectin")
    tickets = relationship(
        "Ticket",
        secondary=ticket_labels,
        back_populates="labels",
        lazy="selectin",
    )