# ⚡ Jarvis AI

### Production-Grade Stateless AI Platform

> A lightweight, secure, multi-provider AI assistant built with Django, SSE streaming, and a controlled autonomous improvement pipeline.

**Stateless · Database-Free · Multi-Provider · SSE Streaming · Security-Focused · Self-Improving**

---

## ✨ Overview

Jarvis AI is a **100% stateless, database-free Django AI assistant platform**.

The browser owns conversation history while Django acts as a thin backend and SSE streaming layer for:

* **Groq**
* **OpenRouter**
* **Ollama**
* **OpenAI**
* Other OpenAI-compatible providers

There is no database, no migrations, and no server-side conversation state.

The project is designed around a simple principle:

> **Keep the application lightweight while making the engineering pipeline increasingly reliable, testable, and safe.**

---

## 🧩 Architecture

```text
                         ┌─────────────────────┐
                         │      Browser UI     │
                         │ Chat + File Zone    │
                         │ Command Palette     │
                         └──────────┬──────────┘
                                    │
                              HTTP / SSE
                                    │
                         ┌──────────▼──────────┐
                         │       Django        │
                         │ Stateless API Layer │
                         └──────────┬──────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
       ┌──────▼──────┐      ┌──────▼──────┐      ┌──────▼──────┐
       │   Provider  │      │    Tools    │      │   Security  │
       │   Layer     │      │   Framework │      │   Controls  │
       └──────┬──────┘      └─────────────┘      └─────────────┘
              │
       ┌──────┼───────────────┬───────────────┐
       │      │               │               │
     Groq  OpenRouter       Ollama          OpenAI
```

### Repository Structure

```text
project-root/
├── backend/
│   ├── ai/
│   │   └── settings.py       # Django configuration & security
│   └── todo/
│       ├── config.py         # Central configuration
│       ├── provider.py       # SSE streaming orchestration
│       ├── provider_adapters.py
│       │                       # Multi-provider abstraction
│       ├── tools.py          # Controlled workspace tools
│       ├── views.py          # API endpoints
│       ├── services.py       # Provider boundary layer
│       └── utils.py          # Retry & request deduplication
│
├── frontend/
│   ├── static/
│   │   ├── css/style.css     # UI, themes & layout
│   │   └── js/chat.js        # SSE client & session logic
│   └── templates/
│       └── todo/
│           ├── index.html
│           └── test_frontend.html
│
├── tests/
│   ├── test_chat_api.py
│   └── test_tools.py
│
├── scripts/
│   ├── validate_env.py
│   └── daily_improvement.py  # Autonomous improvement engine
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   └── daily-improvement.yml
│   └── codex/
│       └── improvement-log.md
│
├── .env.example
├── .gitignore
├── Procfile
├── requirements.txt
├── runtime.txt
└── vercel.json
```

---

## 🤖 Autonomous Daily Improvement Engine

Jarvis includes a controlled automated engineering pipeline designed to make **one small, verified improvement per run**.

### Current flow

```text
┌──────────────────────────────┐
│ Scheduled GitHub Action      │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│ Verify clean repository      │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│ Run baseline validation      │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│ Select unused safe           │
│ improvement from catalog     │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│ Modify target file(s)        │
└──────────────┬───────────────┘
               ↓
┌──────────────────────────────┐
│ Security + syntax + tests    │
└──────────────┬───────────────┘
               ↓
          ┌────┴────┐
          │         │
        PASS       FAIL
          │         │
          ↓         ↓
       Log +      Rollback
       Commit     to baseline
          │
          ↓
         Push
```

The engine is deliberately conservative.

It currently:

* Applies **one verified improvement per run**
* Validates the repository before changing it
* Runs Django system checks
* Runs the complete pytest suite
* Checks modified Python files for syntax errors
* Limits the number of changed files
* Limits the number of changed lines
* Blocks protected files and workflow modifications
* Scans diffs for possible secrets
* Automatically rolls back failed improvements
* Skips already-recorded improvements
* Maintains an improvement history
* Refuses to commit an unvalidated change

### Important Design Boundary

The current engine is **catalog-driven**.

It selects from predefined safe improvements rather than independently inventing arbitrary repository changes.

In other words:

```text
Current:
Catalog → Select → Modify → Verify → Log → Commit

Not currently:
Repository analysis → Discover problem → Design solution
→ Modify dynamically → Verify → Log → Commit
```

This distinction is intentional: **safety currently takes priority over unrestricted autonomy.**

---

## 🔌 Multi-Provider AI

Select the provider using:

```env
AI_PROVIDER=groq
```

| Provider       | Value        | Required Configuration              |
| -------------- | ------------ | ----------------------------------- |
| **Groq**       | `groq`       | `GROQ_API_KEY`                      |
| **OpenRouter** | `openrouter` | `OPENAI_API_KEY`, `OPENAI_BASE_URL` |
| **Ollama**     | `ollama`     | Local Ollama server                 |
| **OpenAI**     | `openai`     | `OPENAI_API_KEY`                    |

All providers pass through a common adapter layer.

Provider failures are normalized into safe categories:

```text
timeout
rate_limit
authentication
validation
provider_failure
```

Credentials are never returned through application errors or logs.

---

## 🌊 SSE Streaming

The backend and frontend use a standardized streaming protocol.

| Event              | Purpose                       |
| ------------------ | ----------------------------- |
| `message_start`    | Initializes the response      |
| `message_delta`    | Sends incremental text        |
| `message_complete` | Signals successful completion |
| `message_error`    | Sends a classified safe error |

A request carries a UUID `request_id` for request tracking and deduplication.

---

## 🛠️ Controlled Tool Framework

Available through `/api/tools/`.

| Tool                | Purpose                      | Protection                    |
| ------------------- | ---------------------------- | ----------------------------- |
| `calculator`        | Safe mathematical evaluation | AST-only                      |
| `repository_search` | Search project files         | Workspace restricted          |
| `file_inspection`   | Inspect project files        | Path containment + size limit |
| `project_metadata`  | Read project metadata        | Read-only                     |

### Safety Rules

* No shell execution
* Schema validation
* Workspace path containment
* Execution time limits
* File-size limits
* Audit logging
* Protected paths
* Secret detection

---

## 🖥️ Developer Workspace

### Command Palette

Press **`Ctrl+K`** / **`Cmd+K`**.

| Command     | Function                      |
| ----------- | ----------------------------- |
| `/new`      | Start a new technical session |
| `/context`  | Toggle File Zone              |
| `/tools`    | Inspect available tools       |
| `/export`   | Export session                |
| `/clear`    | Clear session                 |
| `/settings` | Workbench preferences         |
| `/status`   | Provider readiness            |

### File Zone

Press **`Ctrl+I`**.

Supports:

* Drag & drop files
* Code and text inspection
* Notes / scratchpad
* PDF parsing
* PPTX / DOCX parsing
* Secret detection and redaction
* Project metadata
* Architecture explanation
* Debugging
* Refactoring
* Security auditing
* Test generation

---

## 🔐 Security

Jarvis applies multiple layers of protection:

* CSRF protection
* CORS restrictions
* Rate limiting
* Request-body limits
* Message-size limits
* UUID validation
* Request deduplication
* Secret detection
* Secret redaction
* Privacy-safe structured logging
* Path traversal protection
* Safe health endpoint
* Browser security headers
* Protected autonomous-improvement paths

The autonomous engine additionally refuses modifications to:

```text
.env
.env.example
Procfile
runtime.txt
vercel.json
.github/workflows/*
.git/*
```

---

## 🧪 Testing

Run the complete test suite:

```powershell
$env:PYTHONPATH="backend"
python -m pytest -v
```

Run Django checks:

```bash
python backend/manage.py check
```

Validate the environment:

```bash
python scripts/validate_env.py
```

The autonomous improvement engine also performs baseline and post-change validation before accepting an improvement.

---

## 🚀 Local Development

### 1. Create a virtual environment

```bash
python -m venv .venv
```

### 2. Install dependencies

**Windows**

```powershell
.venv\Scripts\pip install -r requirements.txt
```

### 3. Configure environment

```powershell
copy .env.example .env
```

Add your provider credentials.

### 4. Start Django

```bash
cd backend
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000
```

No database or migrations are required.

---

## 🌍 Deployment

### Render

Build:

```bash
pip install -r requirements.txt && python backend/manage.py collectstatic --noinput
```

Start:

```bash
gunicorn --chdir backend --workers 2 --threads 4 --timeout 120 ai.wsgi:application
```

### Railway

Use the same Gunicorn command or the included `Procfile`.

### Vercel

The repository includes `vercel.json`.

It routes the API through the Django WSGI application while serving frontend assets separately.

> For smoothest SSE streaming, traditional WSGI deployments such as Render or Railway are preferred over serverless environments that may buffer streaming responses.

---

## 📡 API

| Endpoint       | Method | Purpose               |
| -------------- | ------ | --------------------- |
| `/api/chat/`   | `POST` | SSE chat completion   |
| `/api/tools/`  | `GET`  | List registered tools |
| `/api/tools/`  | `POST` | Execute a tool        |
| `/api/health/` | `GET`  | Provider readiness    |

### Chat Request

```json
{
  "message": "Hello Jarvis",
  "history": [],
  "request_id": "uuid"
}
```

Limits currently include:

* Message: **8,000 characters**
* Request body: **256 KB**
* Rate limit: **10 requests/minute/IP**

---

## 🔄 CI/CD

GitHub Actions runs the normal CI pipeline on pushes and pull requests to `main`.

The CI pipeline performs:

```text
Python setup
    ↓
Dependency installation
    ↓
Django system checks
    ↓
Full pytest suite
```

The separate daily-improvement workflow runs the controlled autonomous improvement engine on its schedule.

---

## 📜 Improvement History

Verified autonomous changes are recorded in:

```text
.github/codex/improvement-log.md
```

Each entry records:

```text
Date
Improvement
Target files
Verification status
```

This provides a lightweight audit trail of automated repository changes.

---

## 🎯 Design Philosophy

Jarvis is intentionally built around several constraints:

**Stateless**

No server-side conversation database.

**Provider-Agnostic**

The application should not depend on a single model provider.

**Controlled**

Tools and automated modifications operate inside explicit boundaries.

**Tested**

Changes are accepted only after validation.

**Reversible**

Failed autonomous changes are rolled back.

**Incremental**

The improvement engine makes small changes rather than attempting uncontrolled rewrites.

---

## 📌 Project Status

Jarvis is an actively evolving engineering project.

The core platform currently combines:

```text
Django
+ SSE Streaming
+ Multi-Provider AI
+ Controlled Tools
+ Security Boundaries
+ Automated Testing
+ GitHub CI/CD
+ Controlled Daily Improvements
```

The autonomous improvement system is intentionally **not unrestricted self-modifying AI**. Its current objective is to make small, measurable, verifiable improvements while minimizing the probability of breaking the application.

---

## 📄 License

See the repository license for usage and distribution terms.
