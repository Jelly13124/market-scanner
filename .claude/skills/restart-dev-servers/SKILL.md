---
name: restart-dev-servers
description: Restart only this project's FastAPI and Vite development servers using the active project environment.
disable-model-invocation: true
---

# Restart development servers

Read docs/development.md for current commands. Inspect the port and command line before stopping a process; stop only this project's uvicorn/Vite instances. Never kill all Node/Python processes.

Use the active Python >=3.11 project environment. Run the backend from the root with `poetry run python -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8001`; run `npm run dev` from app/frontend. Read the actual Vite URL from its log rather than assuming an IPv4/IPv6 binding.

Verify GET /health and the frontend URL. A protected endpoint may return 401; do not mistake that for a server outage. Confirm VITE_API_URL matches the backend before diagnosing network failures. Do not change ports or authentication configuration silently.
