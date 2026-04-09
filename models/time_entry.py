import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from database import Base


class TimeEntry(Base):
    __tablename__ = "time_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    hours = Column(Float, nullable=False)
    description = Column(String(255), nullable=True)
    spent_date = Column(Date, nullable=False, default=date.today)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    ticket = relationship("Ticket", back_populates="time_entries", lazy="selectin")
    user = relationship("User", back_populates="time_entries", lazy="selectin")

    def __repr__(self) -> str:
        return f"<TimeEntry(id={self.id}, ticket_id={self.ticket_id}, user_id={self.user_id}, hours={self.hours})>"