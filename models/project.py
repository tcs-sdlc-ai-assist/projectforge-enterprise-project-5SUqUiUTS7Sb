import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from database import Base

if TYPE_CHECKING:
    from models.comment import Comment
    from models.department import Department
    from models.label import Label
    from models.sprint import Sprint
    from models.ticket import Ticket
    from models.time_entry import TimeEntry
    from models.user import User


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(12), unique=True, nullable=False, index=True)
    name = Column(String(200), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(
        Enum("planning", "active", "on_hold", "completed", "archived", name="project_status"),
        default="planning",
        nullable=False,
    )
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    department = relationship("Department", back_populates="projects", lazy="selectin")
    owner = relationship("User", back_populates="owned_projects", foreign_keys=[owner_id], lazy="selectin")
    members = relationship("ProjectMember", back_populates="project", lazy="selectin", cascade="all, delete-orphan")
    sprints = relationship("Sprint", back_populates="project", lazy="selectin", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="project", lazy="selectin", cascade="all, delete-orphan")
    labels = relationship("Label", back_populates="project", lazy="selectin", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, key='{self.key}', name='{self.name}', status='{self.status}')>"

    @property
    def member_count(self) -> int:
        if self.members:
            return len(self.members)
        return 0


class ProjectMember(Base):
    __tablename__ = "project_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(
        Enum("project_manager", "team_lead", "developer", "viewer", name="project_member_role"),
        nullable=False,
        default="developer",
    )
    joined_at = Column(DateTime, default=func.now(), nullable=False)

    # Relationships
    project = relationship("Project", back_populates="members", lazy="selectin")
    user = relationship("User", back_populates="project_memberships", lazy="selectin")

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )

    def __repr__(self) -> str:
        return f"<ProjectMember(id={self.id}, project_id={self.project_id}, user_id={self.user_id}, role='{self.role}')>"