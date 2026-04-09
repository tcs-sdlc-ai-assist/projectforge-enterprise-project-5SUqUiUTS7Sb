# Deployment Guide — ProjectForge on Vercel

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Variables](#environment-variables)
3. [vercel.json Configuration](#verceljson-configuration)
4. [Build Steps](#build-steps)
5. [Database Considerations for Serverless](#database-considerations-for-serverless)
6. [Static Files Serving](#static-files-serving)
7. [Troubleshooting Common Issues](#troubleshooting-common-issues)

---

## Prerequisites

- A [Vercel](https://vercel.com) account
- The [Vercel CLI](https://vercel.com/docs/cli) installed (`npm i -g vercel`)
- Python 3.10 or later
- Git repository connected to Vercel (GitHub, GitLab, or Bitbucket)
- All dependencies listed in `requirements.txt`

---

## Environment Variables

Set the following environment variables in the Vercel dashboard under **Project → Settings → Environment Variables**. Never commit secrets to version control.

| Variable | Required | Example | Description |
|---|---|---|---|
| `SECRET_KEY` | **Yes** | `a3f8b2c1...` (64+ random chars) | Used for JWT signing and session security. Generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | **Yes** | `postgresql+asyncpg://user:pass@host:5432/dbname` | Async database connection string. See [Database Considerations](#database-considerations-for-serverless). |
| `ENVIRONMENT` | No | `production` | Set to `production` for deployed environments. Defaults to `development`. |
| `ALLOWED_ORIGINS` | No | `https://your-app.vercel.app,https://yourdomain.com` | Comma-separated list of allowed CORS origins. |
| `LOG_LEVEL` | No | `INFO` | Python logging level. Defaults to `INFO` in production. |
| `CHROMA_DB_PATH` | No | `/tmp/chroma_db` | Path for ChromaDB persistence. Must be `/tmp/*` on Vercel (see notes below). |

### Setting Variables via CLI

```bash
vercel env add SECRET_KEY production
vercel env add DATABASE_URL production
```

### Local Development with `.env`

Create a `.env` file in the project root (this file is gitignored):

```env
SECRET_KEY=dev-secret-key-change-in-production
DATABASE_URL=sqlite+aiosqlite:///./projectforge.db
ENVIRONMENT=development
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
LOG_LEVEL=DEBUG
```

---

## vercel.json Configuration

Create or verify `vercel.json` in the project root:

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
      "dest": "main.py"
    }
  ],
  "env": {
    "ENVIRONMENT": "production"
  }
}
```

### Key Points

- **`@vercel/python`** — Vercel's Python runtime. It detects `requirements.txt` automatically and installs dependencies.
- **Route ordering matters** — Static file routes must come before the catch-all route so that CSS, JS, and image assets are served directly.
- The entry point (`main.py`) must expose a FastAPI `app` object. Vercel expects the ASGI application at `main:app` or `app:app`.

---

## Build Steps

### 1. Verify Local Build

Before deploying, confirm everything works locally:

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run tests (if applicable)
pytest
```

### 2. Deploy to Vercel

**Option A — Git Push (Recommended)**

Connect your repository in the Vercel dashboard. Every push to `main` triggers an automatic deployment.

```bash
git add .
git commit -m "Deploy to Vercel"
git push origin main
```

**Option B — Vercel CLI**

```bash
# Preview deployment
vercel

# Production deployment
vercel --prod
```

### 3. Post-Deployment Verification

After deployment completes:

```bash
# Check the health endpoint
curl https://your-app.vercel.app/api/health

# Check logs
vercel logs your-app.vercel.app
```

---

## Database Considerations for Serverless

### SQLite Limitations on Vercel

**SQLite CANNOT be used in production on Vercel.** Vercel serverless functions run in ephemeral, read-only file systems. This means:

- The SQLite database file is **destroyed** after each function invocation.
- The `/tmp` directory is writable but **not persistent** across invocations.
- Concurrent function instances do **not share** the same `/tmp` directory.
- Data written to SQLite during one request **will not exist** for the next request.

SQLite is suitable **only** for local development and testing.

### Recommended: External PostgreSQL

Use a managed PostgreSQL provider:

| Provider | Free Tier | Connection String Format |
|---|---|---|
| [Neon](https://neon.tech) | 512 MB | `postgresql+asyncpg://user:pass@ep-xxx.region.aws.neon.tech/dbname?sslmode=require` |
| [Supabase](https://supabase.com) | 500 MB | `postgresql+asyncpg://postgres:pass@db.xxx.supabase.co:5432/postgres` |
| [Railway](https://railway.app) | Trial credits | `postgresql+asyncpg://postgres:pass@host:port/railway` |
| [Vercel Postgres](https://vercel.com/docs/storage/vercel-postgres) | 256 MB | Use `POSTGRES_URL` env var provided by Vercel |

### Connection String Setup

Update `DATABASE_URL` in Vercel environment variables:

```
postgresql+asyncpg://username:password@hostname:5432/database_name?sslmode=require
```

Ensure `asyncpg` is in `requirements.txt`:

```
asyncpg>=0.29.0
```

### Connection Pooling for Serverless

Serverless functions create new database connections on each cold start. To avoid exhausting connection limits:

1. **Use connection pooling** — Neon and Supabase offer built-in connection poolers (PgBouncer). Use the pooled connection string (typically port `6543` instead of `5432`).

2. **Configure SQLAlchemy pool settings** for serverless:

```python
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    DATABASE_URL,
    pool_size=1,          # Minimal pool for serverless
    max_overflow=2,       # Allow small burst
    pool_timeout=30,      # Seconds to wait for connection
    pool_recycle=300,     # Recycle connections every 5 minutes
    pool_pre_ping=True,   # Verify connections before use
)
```

3. **Use NullPool** if connection pooling is handled externally:

```python
from sqlalchemy.pool import NullPool

engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,
)
```

### Database Migrations

Run migrations **before** deploying or as a separate step (not inside serverless functions):

```bash
# Run Alembic migrations against the production database
DATABASE_URL="postgresql+asyncpg://..." alembic upgrade head
```

If not using Alembic, create tables via a one-time script:

```bash
python -c "
import asyncio
from database import engine, Base
from models import *  # Import all models to register them

async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

asyncio.run(init())
"
```

### ChromaDB on Serverless

ChromaDB uses local file storage by default, which has the same limitations as SQLite on Vercel:

- Use `/tmp/chroma_db` as the path — it is writable but **ephemeral**.
- Data will **not persist** across function invocations.
- For production RAG features, consider:
  - [Chroma Cloud](https://www.trychroma.com/) (managed service)
  - [Pinecone](https://www.pinecone.io/) as an alternative vector database
  - Pre-building and bundling a read-only ChromaDB collection in the deployment package (for static knowledge bases)

---

## Static Files Serving

### Directory Structure

```
project-root/
├── static/
│   ├── css/
│   │   └── styles.css
│   ├── js/
│   │   └── app.js
│   └── images/
│       └── logo.png
├── templates/
│   └── base.html
├── main.py
├── vercel.json
└── requirements.txt
```

### FastAPI Static Mount

In `main.py`, mount the static directory:

```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
```

### Template References

In Jinja2 templates, reference static files with absolute paths:

```html
<link rel="stylesheet" href="/static/css/styles.css">
<script src="/static/js/app.js"></script>
<img src="/static/images/logo.png" alt="Logo">
```

### Vercel Static File Routing

The `vercel.json` routes configuration (shown above) ensures that requests to `/static/*` are served directly without hitting the Python runtime, improving performance.

---

## Troubleshooting Common Issues

### 1. `ModuleNotFoundError: No module named 'xyz'`

**Cause:** Missing dependency in `requirements.txt`.

**Fix:** Ensure all dependencies are listed:

```bash
pip freeze > requirements.txt
```

Or manually verify that every imported third-party package is in `requirements.txt`. Common missing packages:

- `python-multipart` — Required for `Form()` data parsing
- `pydantic-settings` — Required for `BaseSettings`
- `python-dotenv` — Required by pydantic-settings for `.env` loading
- `aiosqlite` — Required for async SQLite (development only)
- `asyncpg` — Required for async PostgreSQL (production)

### 2. `Internal Server Error` (500) with No Logs

**Cause:** The ASGI app object is not found.

**Fix:** Verify that `main.py` exposes the FastAPI app at module level:

```python
# main.py
from fastapi import FastAPI

app = FastAPI()

# Vercel looks for `app` in the module specified by vercel.json
```

### 3. `CORS Error` in Browser Console

**Cause:** The deployed frontend origin is not in the allowed origins list.

**Fix:** Add your Vercel deployment URL to `ALLOWED_ORIGINS`:

```
ALLOWED_ORIGINS=https://your-app.vercel.app,https://your-custom-domain.com
```

Verify CORS middleware configuration in `main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,  # List of allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 4. `Function Timeout` (10s / 60s limit)

**Cause:** Serverless functions on Vercel have execution time limits (10s on Hobby, 60s on Pro).

**Fix:**
- Optimize database queries — add indexes, use pagination, avoid N+1 queries.
- Move long-running tasks to background job services (e.g., Vercel Cron Jobs, external task queues).
- Reduce cold start time by minimizing dependencies.

### 5. `Read-only file system` Error

**Cause:** Attempting to write files outside `/tmp`.

**Fix:** All file writes must target `/tmp/`:

```python
import tempfile
from pathlib import Path

WRITABLE_DIR = Path(tempfile.gettempdir())
```

Remember that `/tmp` is ephemeral — files do not persist across invocations.

### 6. `MissingGreenlet` Error at Runtime

**Cause:** Lazy-loaded SQLAlchemy relationships accessed outside an async context (e.g., in Jinja2 templates).

**Fix:** Ensure ALL `relationship()` declarations use `lazy="selectin"`:

```python
class Project(Base):
    tasks = relationship("Task", back_populates="project", lazy="selectin")
```

And use `selectinload()` in queries when accessing nested relationships:

```python
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(Project).options(selectinload(Project.tasks))
)
```

### 7. `Connection refused` or `too many connections` (PostgreSQL)

**Cause:** Serverless functions opening too many database connections.

**Fix:**
- Use the pooled connection string from your database provider.
- Set `pool_size=1` and `max_overflow=2` in SQLAlchemy engine config.
- Consider using `NullPool` with an external connection pooler.

### 8. Template Not Found (`TemplateNotFound: base.html`)

**Cause:** Jinja2Templates directory path is relative and resolves incorrectly on Vercel.

**Fix:** Always use absolute paths:

```python
from pathlib import Path
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
```

### 9. Environment Variables Not Loading

**Cause:** Variables set in `.env` are not available on Vercel (`.env` is gitignored).

**Fix:** Set all production variables in the Vercel dashboard or via CLI:

```bash
vercel env ls              # List current variables
vercel env add VAR_NAME    # Add a new variable
vercel env rm VAR_NAME     # Remove a variable
```

After changing environment variables, **redeploy** for changes to take effect:

```bash
vercel --prod
```

### 10. Slow Cold Starts

**Cause:** Large dependency tree or heavy initialization logic.

**Fix:**
- Remove unused packages from `requirements.txt`.
- Defer heavy imports (e.g., ML models, ChromaDB) to first use rather than module level.
- Use Vercel's **Fluid Functions** or **Edge Functions** where applicable for faster cold starts.
- Keep the deployment package small — exclude test files, documentation, and development tools.

---

## Production Checklist

Before going live, verify:

- [ ] `SECRET_KEY` is a strong, unique random value (not the development default)
- [ ] `DATABASE_URL` points to a managed PostgreSQL instance (not SQLite)
- [ ] `ENVIRONMENT` is set to `production`
- [ ] `ALLOWED_ORIGINS` contains only your actual frontend domains
- [ ] CORS middleware does **not** use `allow_origins=["*"]`
- [ ] Database migrations have been applied to the production database
- [ ] All sensitive environment variables are set in Vercel dashboard
- [ ] `.env` file is in `.gitignore` and not committed
- [ ] Static files are accessible at `/static/*`
- [ ] Health check endpoint responds at `/api/health`
- [ ] Error logging is configured and accessible via `vercel logs`
- [ ] Password hashing uses bcrypt (not plain text)
- [ ] JWT tokens have a reasonable expiration time