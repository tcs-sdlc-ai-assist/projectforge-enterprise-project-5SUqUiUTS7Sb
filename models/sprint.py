import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from database import Base


class Sprint(Base):
    __tablename__ = "sprints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    goal = Column(Text, nullable=True)
    status = Column(
        Enum("planning", "active", "completed", name="sprint_status"),
        default="planning",
        nullable=False,
    )
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    project = relationship("Project", back_populates="sprints", lazy="selectin")
    tickets = relationship("Ticket", back_populates="sprint", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Sprint(id={self.id}, name='{self.name}', status='{self.status}')>"