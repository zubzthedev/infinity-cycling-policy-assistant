# Ask Oufy

Infinity Cycling Club Policy Assistant — an internal governance and policy
assistant for the club's Executive Committee.

This is a work in progress, being built milestone by milestone. A
comprehensive README (architecture, setup, deployment, administration,
troubleshooting) will be added in the final documentation milestone.

## Local development (current state)

```bash
python -m venv .venv
./.venv/Scripts/activate   # or `source .venv/bin/activate` on macOS/Linux
pip install -r requirements-dev.txt
cp .env.example .env       # fill in real values as later milestones require them
uvicorn app.main:app --reload
```

Then visit `http://127.0.0.1:8000/api/health`.
