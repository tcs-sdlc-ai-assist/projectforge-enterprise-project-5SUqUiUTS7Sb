import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import logging

from passlib.context import CryptContext
from sqlalchemy import select

from config import settings
from database import async_session_factory
from models.user import User
from models.department import Department

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def seed_database() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.username == settings.DEFAULT_ADMIN_USERNAME)
            )
            admin_user = result.scalars().first()

            if admin_user is None:
                admin_user = User(
                    username=settings.DEFAULT_ADMIN_USERNAME,
                    email=f"{settings.DEFAULT_ADMIN_USERNAME}@projectforge.local",
                    full_name="System Administrator",
                    password_hash=pwd_context.hash(settings.DEFAULT_ADMIN_PASSWORD),
                    role="super_admin",
                    is_active=True,
                )
                session.add(admin_user)
                await session.flush()
                logger.info(
                    "Created default admin user: %s", settings.DEFAULT_ADMIN_USERNAME
                )
            else:
                logger.info(
                    "Default admin user already exists: %s",
                    settings.DEFAULT_ADMIN_USERNAME,
                )

            result = await session.execute(
                select(Department).where(Department.code == "ENG")
            )
            eng_department = result.scalars().first()

            if eng_department is None:
                eng_department = Department(
                    name="Engineering",
                    code="ENG",
                    description="Engineering department responsible for software development and technical operations.",
                    head_id=admin_user.id,
                )
                session.add(eng_department)
                await session.flush()
                logger.info("Created Engineering department with code ENG")
            else:
                logger.info("Engineering department already exists")

            if admin_user.department_id is None:
                admin_user.department_id = eng_department.id
                logger.info(
                    "Assigned admin user '%s' to Engineering department",
                    admin_user.username,
                )

        await session.commit()
        logger.info("Database seeding completed successfully")