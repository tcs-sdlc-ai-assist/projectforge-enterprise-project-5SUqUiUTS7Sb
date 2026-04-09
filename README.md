# ProjectForge

**AI-Powered Project Management Platform**

A comprehensive project management tool built with Python, FastAPI, and Tailwind CSS that helps teams plan, track, and deliver projects efficiently with intelligent automation features.

---

## Features

- **Project Management** — Create, organize, and track projects with customizable workflows
- **Sprint Planning** — Plan and manage sprints with drag-and-drop task assignment
- **Ticket Tracking** — Full-featured ticket system with priorities, labels, and status tracking
- **Team Collaboration** — Real-time comments, mentions, and activity feeds
- **Role-Based Access Control** — Granular permissions with multiple user roles
- **AI-Powered Suggestions** — Intelligent task estimation, duplicate detection, and smart search via RAG pipeline
- **Document Management** — Upload, store, and semantically search project documents
- **Dashboard & Analytics** — Visual project health metrics, burndown charts, and velocity tracking
- **Audit Logging** — Complete activity history for compliance and accountability
- **Email Notifications** — Configurable alerts for assignments, status changes, and deadlines

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.10+, FastAPI |
| **Database** | SQLAlchemy 2.0 (async), SQLite / PostgreSQL |
| **Vector DB** | ChromaDB (RAG / semantic search) |
| **Auth** | JWT (python-jose), bcrypt |
| **Templates** | Jinja2 |
| **Styling** | Tailwind CSS |
| **Validation** | Pydantic v2 |
| **Server** | Uvicorn |

---

## Folder Structure

```
projectforge/
├── main.py                  # FastAPI application entry point
├── config.py                # Pydantic Settings configuration
├── database.py              # Async SQLAlchemy engine & session setup
├── requirements.txt         # Python dependencies
├── .env                     # Environment variables (not committed)
├── .env.example             # Example environment variables
├── README.md                # This file
│
├── models/                  # SQLAlchemy ORM models
│   ├── __init__.py
│   ├── user.py
│   ├── project.py
│   ├── sprint.py
│   ├── ticket.py
│   ├── comment.py
│   ├── label.py
│   ├── document.py
│   ├── activity_log.py
│   └── notification.py
│
├── schemas/                 # Pydantic request/response schemas
│   ├── __init__.py
│   ├── user.py
│   ├── project.py
│   ├── sprint.py
│   ├── ticket.py
│   ├── comment.py
│   ├── document.py
│   └── notification.py
│
├── routes/                  # FastAPI route handlers
│   ├── __init__.py
│   ├── auth.py
│   ├── users.py
│   ├── projects.py
│   ├── sprints.py
│   ├── tickets.py
│   ├── comments.py
│   ├── documents.py
│   ├── dashboard.py
│   ├── notifications.py
│   └── pages.py             # Jinja2 template-serving routes
│
├── services/                # Business logic layer
│   ├── __init__.py
│   ├── auth_service.py
│   ├── user_service.py
│   ├── project_service.py
│   ├── ticket_service.py
│   ├── sprint_service.py
│   ├── document_service.py
│   ├── notification_service.py
│   └── rag_service.py       # ChromaDB / vector search logic
│
├── dependencies/            # FastAPI dependency injection
│   ├── __init__.py
│   ├── auth.py              # JWT token verification, get_current_user
│   └── database.py          # get_db session dependency
│
├── templates/               # Jinja2 HTML templates
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── projects/
│   │   ├── list.html
│   │   ├── detail.html
│   │   └── create.html
│   ├── tickets/
│   │   ├── list.html
│   │   ├── detail.html
│   │   └── create.html
│   ├── sprints/
│   │   ├── board.html
│   │   └── detail.html
│   └── partials/
│       ├── sidebar.html
│       ├── header.html
│       └── notifications.html
│
├── static/                  # Static assets
│   ├── css/
│   │   └── output.css       # Compiled Tailwind CSS
│   └── js/
│       └── app.js
│
├── migrations/              # Alembic database migrations
│   └── ...
│
└── tests/                   # Test suite
    ├── conftest.py
    ├── test_auth.py
    ├── test_projects.py
    ├── test_tickets.py
    └── test_sprints.py
```

---

## Setup Instructions

### Prerequisites

- Python 3.10 or higher
- pip (Python package manager)
- Node.js (optional, for Tailwind CSS compilation)

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/projectforge.git
cd projectforge
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```env
# Application
APP_NAME=ProjectForge
APP_ENV=development
DEBUG=true
SECRET_KEY=your-secret-key-min-32-characters-long

# Database
DATABASE_URL=sqlite+aiosqlite:///./projectforge.db

# JWT
JWT_SECRET_KEY=your-jwt-secret-key-min-32-characters
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

# ChromaDB
CHROMA_DB_PATH=./chroma_data

# OpenAI (for embeddings / AI features)
OPENAI_API_KEY=sk-your-openai-api-key

# CORS
CORS_ORIGINS=["http://localhost:8000","http://127.0.0.1:8000"]
```

### 5. Initialize the Database

```bash
python -c "from database import init_db; import asyncio; asyncio.run(init_db())"
```

Or if using Alembic migrations:

```bash
alembic upgrade head
```

### 6. Run the Application

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The application will be available at **http://localhost:8000**.

API documentation is auto-generated at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## Usage Guide

### Getting Started

1. **Register** — Navigate to `/register` to create your account. The first registered user is automatically assigned the `super_admin` role.
2. **Login** — Sign in at `/login` with your credentials.
3. **Create a Project** — From the dashboard, click "New Project" and fill in the project details.
4. **Add Team Members** — Invite users to your project and assign roles.
5. **Create Sprints** — Set up time-boxed sprints for iterative delivery.
6. **Create Tickets** — Add tasks, bugs, and stories to your project backlog.
7. **Track Progress** — Use the dashboard and sprint board to monitor project health.

### API Usage

All API endpoints are available under the `/api/v1` prefix. Authenticate by including a JWT token in the `Authorization` header:

```bash
# Login to get a token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "yourpassword"}'

# Use the token for authenticated requests
curl http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer <your-access-token>"
```

---

## User Roles

| Role | Description | Permissions |
|---|---|---|
| **Super Admin** | Platform administrator | Full access to all projects, users, and settings |
| **Project Manager** | Manages one or more projects | Create/edit projects, manage sprints, assign tickets, manage team members |
| **Developer** | Team member working on tasks | View projects, update assigned tickets, add comments, log time |
| **Viewer** | Read-only stakeholder | View projects, tickets, and reports; add comments only |

---

## Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_auth.py

# Run with coverage report
pytest --cov=. --cov-report=html
```

---

## Deployment

### Vercel Deployment

ProjectForge can be deployed to Vercel as a serverless Python application.

1. **Install the Vercel CLI:**

   ```bash
   npm install -g vercel
   ```

2. **Create `vercel.json` in the project root:**

   ```json
   {
     "version": 2,
     "builds": [
       {
         "src": "main.py",
         "use": "@vercel/python"
       }
     ],
     "routes": [
       {
         "src": "/static/(.*)",
         "dest": "/static/$1"
       },
       {
         "src": "/(.*)",
         "dest": "/main.py"
       }
     ]
   }
   ```

3. **Set environment variables** in the Vercel dashboard under Project Settings → Environment Variables. Add all variables from your `.env` file.

4. **Deploy:**

   ```bash
   vercel --prod
   ```

> **Note:** For production deployments, switch from SQLite to PostgreSQL by updating `DATABASE_URL` to use `postgresql+asyncpg://...` and ensure `asyncpg` is in your `requirements.txt`.

### Docker Deployment

```bash
docker build -t projectforge .
docker run -p 8000:8000 --env-file .env projectforge
```

---

## Contributing

This is a private project. Contributions are accepted only from authorized team members. Please follow the established code style and ensure all tests pass before submitting a pull request.

---

## License

**Private and Proprietary**

Copyright © 2024 ProjectForge. All rights reserved.

This software is proprietary and confidential. Unauthorized copying, distribution, modification, or use of this software, via any medium, is strictly prohibited. This software is provided under a private license and may only be used by authorized individuals or organizations with explicit written permission from the copyright holder.

No part of this software may be reproduced, distributed, or transmitted in any form or by any means without the prior written permission of the copyright holder.