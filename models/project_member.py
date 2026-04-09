import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import relationship

from database import Base


class ProjectMember(Base):
    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(
        Enum("owner", "manager", "member", "observer", name="project_member_role"),
        nullable=False,
        default="member",
    )
    joined_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member_project_user"),
    )

    project = relationship("Project", back_populates="members", lazy="selectin")
    user = relationship("User", back_populates="project_memberships", lazy="selectin")

    def __repr__(self) -> str:
        return f"<ProjectMember(id={self.id}, project_id={self.project_id}, user_id={self.user_id}, role='{self.role}')>"