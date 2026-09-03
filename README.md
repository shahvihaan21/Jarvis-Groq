# Jarvis AI — Production-Grade Stateless AI Platform

A 100% stateless, database-free Django AI assistant platform. The browser owns the conversation
history (JS array); Django is a thin SSE proxy that streams tokens from
**Groq**, **OpenRouter**, **Ollama**, or any **OpenAI-compatible** provider.
No database, no migrations, no server-side state — deploy anywhere.

## Architecture

```
project-root/
├── backend/
│   ├── ai/                    # Settings, URLs, WSGI
│   └── todo/
│       ├── config.py          # Centralized configuration (timeouts, limits, system prompt)
│       ├── provider.py        # SSE streaming orchestrator
│       ├── provider_adapters.py  # Multi-provider abstraction (Groq, OpenAI-compatible, Ollama)
│       ├── tools.py           # Controlled tool framework (calculator, repo search, file inspect)
│       ├── views.py           # Thin stateless views + health + tools API
│       ├── services.py        # Provider boundary compatibility layer
│       └── utils.py           # Retry logic & request dedup
├── frontend/
│   ├── static/
│   │   ├── css/style.css      # Dark/light theme, resizable sidebar, command palette
│   │   └── js/chat.js         # SSE engine, file attachment, session persistence
│   └── templates/
│       └── todo/
│           ├── index.html     # Main workspace UI
│           └── test_frontend.html  # Browser-side test suite
├── tests/
│   ├── test_chat_api.py       # 12 API & streaming tests
│   └── test_tools.py          # 9 tool & security boundary tests
├── scripts/
│   └── validate_env.py        # Pre-deployment environment validator
├── .github/workflows/ci.yml   # GitHub Actions CI pipeline
├── .env.example
├── .gitignore
├── Procfile
├── requirements.txt
└── runtime.txt
```

## Multi-Provider System

Jarvis supports configuration-driven provider selection via the `AI_PROVIDER` environment variable:

| Provider | `AI_PROVIDER` | Required Env Vars |
|---|---|---|
| **Groq** (default) | `groq` | `GROQ_API_KEY` |
| **OpenRouter** | `openrouter` | `OPENAI_API_KEY`, `OPENAI_BASE_URL` |
| **Ollama** (local) | `ollama` | None (defaults to `http://localhost:11434/v1`) |
| **OpenAI** | `openai` | `OPENAI_API_KEY` |

Provider adapters normalize all upstream errors into safe application categories (`timeout`, `rate_limit`, `authentication`, `validation`, `provider_failure`). Credentials are never exposed in logs, responses, or error messages.

## SSE Streaming Protocol

All streaming uses a standardized event protocol shared between backend and frontend:

| Event | Description |
|---|---|
| `message_start` | Stream initialized with `request_id`, `model`, `provider`, `timestamp` |
| `message_delta` | Incremental text chunk (`delta` field) |
| `message_complete` | Stream finished with `duration_ms` and `token_count` |
| `message_error` | Classified error with `category` and user-safe `error` message |

## Controlled Tool Framework

Safe, bounded workspace tools accessible via `/api/tools/`:

| Tool | Description | Safety |
|---|---|---|
| `calculator` | Safe AST math evaluation | No code execution, AST-only |
| `repository_search` | Search project files by name | Workspace-restricted |
| `file_inspection` | Read project file contents | Path traversal protected, 500KB limit |
| `project_metadata` | Framework, language, provider info | Read-only metadata |

Shell execution is **strictly prohibited**. All tools enforce schema validation, 5-second timeouts, path containment, and audit logging.

## Developer Command Palette

Press `Ctrl+K` (or `Cmd+K`) to open the command palette:

| Command | Action |
|---|---|
| `/new` | Start a new technical session |
| `/context` | Toggle File Zone |
| `/tools` | Inspect available workspace tools |
| `/export` | Export session as Markdown or JSON |
| `/clear` | Clear active session history |
| `/settings` | Workbench preferences |
| `/status` | Check provider readiness |

## File Zone

The slidable File Zone (`Ctrl+I`) supports:

- **Drag & drop** files (code, text, logs, and configuration)
- **Notes area**: a single paste-anywhere scratchpad for notes, requirements, logs, or config
- **Document parsing**: PDF (via `pdf.js`), PPTX and DOCX (via `JSZip`)
- **Secret detection**: Auto-redacts API keys, tokens, passwords to `[REDACTED_SECRET]`
- **Project metadata**: Name, tech stack, target environment
- **Quick commands**: Explain Architecture, Debug Stacktrace, Refactor Code, Security Audit, Generate Tests

## Local Development

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
copy .env.example .env                           # add your GROQ_API_KEY

cd backend
python manage.py runserver
```

Open http://127.0.0.1:8000 — no migrations or database setup required, ever.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Get one at https://console.groq.com/keys |
| `SECRET_KEY` | Yes (prod) | Random Django secret key |
| `DEBUG` | No | Default `False` — keep off in production |
| `AI_PROVIDER` | No | Default `groq`; options: `groq`, `openrouter`, `ollama`, `openai` |
| `GROQ_MODEL` | No | Default `openai/gpt-oss-120b`; override with available model |
| `ALLOWED_HOSTS` | No prod | Comma-separated hostnames |
| `CSRF_TRUSTED_ORIGINS` | No prod | Comma-separated origins (`https://...`) |

## Deploying to Render

1. Push this repo to GitHub.
2. In Render: **New → Web Service**, connect the repo.
3. Settings:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt && python backend/manage.py collectstatic --noinput`
   - **Start Command**: `gunicorn --chdir backend --workers 2 --threads 4 --timeout 120 ai.wsgi:application`
4. Add environment variables: `GROQ_API_KEY`, `SECRET_KEY`, `DEBUG=False`,
   `ALLOWED_HOSTS=<your-app>.onrender.com`, `CSRF_TRUSTED_ORIGINS=https://<your-app>.onrender.com`.
5. Deploy. Render reads `runtime.txt` for the Python version.

## Deploying to Railway

1. Push the repo, then in Railway: **New Project → Deploy from GitHub repo**.
2. Railway auto-detects Python; ensure the start command is
   `gunicorn --chdir backend --workers 2 --threads 4 --timeout 120 ai.wsgi:application`
   (or use the included `Procfile`).
3. In **Variables**, add `GROQ_API_KEY`, `SECRET_KEY`, `DEBUG=False`,
   `ALLOWED_HOSTS=<yourapp>.up.railway.app`, `CSRF_TRUSTED_ORIGINS=https://<yourapp>.up.railway.app`.
4. Build command: `pip install -r requirements.txt && python backend/manage.py collectstatic --noinput`.

## Deploying to Vercel (Serverless)

The repository already includes `vercel.json`. It routes `/api/index.py` to the
Django WSGI application and serves `frontend/static` directly, so do not replace
it with a WSGI-only configuration or the frontend assets will stop loading.

Note: serverless platforms buffer streaming responses inconsistently; Render/Railway
(WSGI) give the smoothest SSE token streaming. Set `GROQ_API_KEY` and `SECRET_KEY`
as project env vars, and set `ALLOWED_HOSTS=.vercel.app`.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/chat/` | POST | SSE streaming chat completion |
| `/api/tools/` | GET | List registered tool schemas |
| `/api/tools/` | POST | Execute a registered tool |
| `/api/health/` | GET | Provider readiness check (no secrets) |

`POST /api/chat/` accepts JSON with `message`, `history`, and a UUID `request_id`.
It returns an SSE stream of `message_start`, `message_delta`, `message_complete`, or `message_error` events.
Messages are limited to 8,000 characters, request bodies to 256 KB, and the endpoint
is rate-limited to 10 requests per minute per IP.

## Security

- CSRF protection on all form endpoints
- CORS restrictions via `django-cors-headers`
- Rate limiting via `django-ratelimit` (10 req/min/IP)
- Request payload size limits (256 KB)
- UUID request ID validation and deduplication
- Client-side secret detection and auto-redaction
- Privacy-safe structured JSON logging (no API keys, prompts, or credentials)
- Path traversal protection on file inspection tools
- Safe health endpoint (no environment variable exposure)

## Testing

```bash
# Run full test suite (21 tests)
$env:PYTHONPATH="backend"; python -m pytest -v

# Django system checks
python backend/manage.py check

# Environment validation
python scripts/validate_env.py
```

## CI/CD

GitHub Actions CI pipeline (`.github/workflows/ci.yml`) runs on every push/PR to `main`:
- Python 3.12 setup with pip caching
- Django system checks
- Full pytest suite execution
