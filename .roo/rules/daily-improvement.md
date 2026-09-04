# Daily Improvement Agent (Roo)

When asked to perform a "daily improvement", "auto-improvement", or repository maintenance:

1. Follow the policy in `.github/codex/daily-improvement.md` — exactly ONE minor, safe improvement per run.
2. Run the engine directly when possible:
   - Dry run / validation: `python scripts/daily_improvement.py --dry-run`
   - Health check only: `python scripts/daily_improvement.py --check-only`
   - Commit without pushing: `python scripts/daily_improvement.py --no-push`
3. Never modify secrets, `.env`, deployment configs (`vercel.json`, `Procfile`, `runtime.txt`), or `.github/workflows/`.
4. Limits: max 5 changed files, 150 changed lines, commit message `chore: daily improvement - <summary> [skip ci]`.
5. All improvements must pass `pytest` and `python backend/manage.py check` before committing; roll back on failure.
6. Append completed improvements to `.github/codex/improvement-log.md`.
