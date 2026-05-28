---
name: restart-dev-servers
description: Restart the ai-hedge-fund backend (uvicorn :8001) and frontend (vite :5173) cleanly, honoring this repo's Windows-specific gotchas (no --reload, IPv6 frontend, selective process kill). Use when the user says "restart frontend backend", "重启前端后端", "restart the servers", or after backend code changes that need a reload.
disable-model-invocation: true
---

# Restart dev servers

Restart the two ai-hedge-fund dev servers cleanly. This repo has Windows-specific
constraints (see CLAUDE.md) that a naive restart violates.

## Hard rules (load-bearing)

- **NEVER use `--reload`** on uvicorn. On Windows the reloader buffers child
  stdout (request logs never appear) AND leaks the listening socket on
  force-kill. After ~5 kill/restart cycles the port is stuck until reboot.
- **Frontend binds to IPv6 `::1` only.** Verify it with `curl http://localhost:5173`,
  NOT `http://127.0.0.1:5173` (the latter returns 000 even when vite is healthy).
- **Kill selectively.** There are usually other `node` processes running (MCP
  servers, a separate vpn-portal vite, Codex kernels). Only kill the
  ai-hedge-fund vite + its npm parent, and any uvicorn on :8001.

## Steps

### 1. Find what's running

```
netstat -ano | findstr ":8001 :5173"
```
And identify the ai-hedge-fund node/python procs (match the command line):
```powershell
Get-Process python,node -ErrorAction SilentlyContinue | Select-Object Id, ProcessName, @{n='CmdLine';e={(Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine}} | Format-Table -Wrap -AutoSize
```
The frontend to kill is the one whose CmdLine contains
`ai-hedge-fund\app\frontend\node_modules\.bin\..\vite`. The backend is any
`uvicorn app.backend.main:app` on port 8001.

### 2. Kill only those PIDs

```powershell
Stop-Process -Id <vite_pid>,<npm_parent_pid>,<uvicorn_pid> -Force -ErrorAction SilentlyContinue
```
Do NOT kill the MCP node procs, the vpn-portal vite, or Codex kernels.

### 3. Start backend (background, NO --reload)

Run with the Bash tool, `run_in_background: true`:
```
PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 /c/Users/Jerry/anaconda3/python.exe -m uvicorn app.backend.main:app --host 127.0.0.1 --port 8001 --log-level info
```

### 4. Start frontend (background)

Run with the Bash tool, `run_in_background: true`:
```
cd app/frontend && npm run dev
```

### 5. Verify (vite cold start takes ~20s)

Read the background output files until vite prints "ready", then:
```
curl -s -o /dev/null -w "Backend: %{http_code}\n"  http://127.0.0.1:8001/screener/snapshot/status
curl -s -o /dev/null -w "Frontend: %{http_code}\n" http://localhost:5173/
```
Both should be `200`. (Frontend MUST be probed at `localhost`, not `127.0.0.1`.)

## If port 8001 leaked

Don't fight it. Switch backend to the next port (8002, 8003, …) and update
`app/frontend/.env.local` so `VITE_API_URL` matches. Faster than waiting for
Windows to release the socket.

## Report

Tell the user the two URLs + their HTTP status, and remind them the backend log
shows the registered cron jobs (scanner 21:00, pipeline 16:30, research 16:35,
screener_snapshot 22:00 ET).
