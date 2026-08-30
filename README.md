# Jarvis AI — Stateless Groq-Powered Django Assistant

A 100% stateless, database-free Django chat app. The browser owns the conversation
history (JS array); Django is a thin SSE proxy that streams tokens from the
**Groq API**. No database, no migrations, no server-side state — deploy anywhere.

## Architecture

```
project-root/
├── backend/
│   ├── ai/            # Settings, URLs, WSGI
│   └── todo/          # Stateless views + Groq SSE streaming
├── frontend/
│   ├── static/        # CSS + JS (client-side chatHistory array)
│   └── templates/     # HTML
├── .env.example
├── .gitignore
├── Procfile
├── requirements.txt
└── runtime.txt
```

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
| `GROQ_MODEL` | No | Default `llama-3.3-70b-versatile` (or `mixtral-8x7b-32768`) |
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

Add a `vercel.json` at the repo root:

```json
{
  "builds": [{ "src": "backend/ai/wsgi.py", "use": "@vercel/python", "config": { "maxLambdaSize": "15mb" } }],
  "routes": [{ "src": "/(.*)", "dest": "backend/ai/wsgi.py" }]
}
```

Note: serverless platforms buffer streaming responses inconsistently; Render/Railway
(WSGI) give the smoothest SSE token streaming. Set `GROQ_API_KEY` and `SECRET_KEY`
as project env vars, and set `ALLOWED_HOSTS=.vercel.app`.

## How It Works

1. `chat.js` keeps the whole conversation in a local `chatHistory` array.
2. Every send POSTs `{ message, history }` to `/api/chat/`.
3. Django sanitises the history (roles, length caps) and streams the Groq
   completion straight back to the browser as SSE events (`init`, `chunk`, `done`).
4. Nothing touches a disk or database — restart/redeploy loses nothing that matters,
   and scaling is trivially horizontal.

## API

`POST /api/chat/` accepts JSON with `message`, `history`, and a UUID `request_id`.
It returns an SSE stream containing `init`, `chunk`, `done`, or `error` events.
Messages are limited to 8,000 characters, request bodies to 256 KB, and the endpoint
is limited to 10 requests per minute per IP. Reusing a request ID is rejected to
prevent accidental duplicate submissions.

Run `python backend/validate_env.py` before deployment to validate `.env`.
Markdown output is sanitized in the browser with DOMPurify, and static assets are
served with compression and a one-hour cache lifetime. Configure
`CORS_ALLOWED_ORIGINS` explicitly when the frontend is hosted on another origin.

## Quality checks

```bash
pytest
python backend/manage.py check --deploy
```
