# Market Scanner

A stock screening, event scanning, AI research, and historical backtesting application. The backend uses Python/FastAPI; the frontend uses React/Vite. AI analysis uses **LangChain for model calls and structured output**, with **LangGraph for workflow orchestration**.

This guide walks through running the application locally with **PostgreSQL and no MongoDB**. You do not need to rent a server or install PostgreSQL directly on your operating system: Docker runs the database, while Python and Node.js run the application.

## What you need

| Component | Requirement | Purpose |
| --- | --- | --- |
| Git | Installed | Download and update the source |
| Python | 3.11 or newer; the examples use 3.12 | Run the backend |
| Poetry | Installed and available in your terminal | Manage Python dependencies |
| Node.js / npm | Node.js 22 or newer | Install and run the frontend |
| Docker with Compose v2 | Running; Docker Desktop works for local development | Run PostgreSQL 16 |
| Internet access | Required for dependency downloads and online market data | Fetch historical bars and other evidence |
| Model access | Your own provider API key, or a running Ollama model | Generate AI research reports |

**PostgreSQL is required by the course version. MongoDB is optional.** Without MongoDB, the application retrieves market data online and keeps supported application records in PostgreSQL. There is no automatic SQLite fallback for normal application use.

You can start the application, register, manage watchlists, and run historical backtests before configuring an AI model. Full AI reports require model access. Paper trading is under development and unavailable to users.

## 1. Install the development tools

The commands below use **Bash or Zsh**. On Windows, use WSL2 with Docker Desktop's WSL integration; run the project commands inside WSL rather than copying them directly into PowerShell.

On macOS, if Homebrew is already installed, you can install the tools with:

```bash
brew install git python@3.12 node@22 pipx
pipx ensurepath
pipx install poetry
brew install --cask docker
```

Skip any tools you already have. Open Docker Desktop and wait for its engine to start. After installing tools, open a new terminal so PATH changes take effect. If Homebrew's `node@22` is not on PATH, follow the instructions shown by `brew info node@22`.

On Linux or WSL, install the same tools using your distribution's package manager or their installers, including the Docker Compose v2 plugin. The remaining project setup is the same.

Check that the tools are available:

```bash
git --version
python3.12 --version
poetry --version
node --version
npm --version
docker compose version
docker info --format '{{.ServerVersion}}'
```

If your Python executable has a different name, replace `python3.12` in the commands below with your installed Python 3.11+ executable. Do not use an older system Python such as 3.9.

## 2. Download the project and install backend dependencies

```bash
git clone https://github.com/Jelly13124/market-scanner.git
cd market-scanner
poetry env use python3.12
poetry install
poetry run python --version
```

Run subsequent backend and Docker commands from this **repository root**. Frontend commands explicitly change into `app/frontend`.

If you already have the repository, use your existing checkout rather than cloning another copy. For an existing database, follow [Updating an existing installation](#updating-an-existing-installation) before starting the new version.

## 3. Create your local configuration

Copy the example only if you do not already have a `.env` file:

```bash
[ -f .env ] || cp .env.example .env
```

Generate three separate values:

```bash
# PostgreSQL password: copy this output into both password locations below.
poetry run python -c 'import secrets; print(secrets.token_hex(24))'

# JWT signing secret.
poetry run python -c 'import secrets; print(secrets.token_urlsafe(48))'

# Encryption key for model API keys saved through Settings.
poetry run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Open `.env` in your editor and set the following fields. Replace the uppercase placeholders with the generated values; do not leave the placeholder text in the file.

```dotenv
ENVIRONMENT=development
REQUIRE_EMAIL_VERIFICATION=false

POSTGRES_DB=market_scanner
POSTGRES_USER=market_scanner
POSTGRES_PASSWORD=PASTE_DATABASE_PASSWORD
DATABASE_URL=postgresql+psycopg2://market_scanner:PASTE_DATABASE_PASSWORD@127.0.0.1:5433/market_scanner

JWT_SECRET=PASTE_JWT_SECRET
APP_ENCRYPTION_KEY=PASTE_FERNET_KEY

SCANNER_DATA_PROVIDER=hybrid
MONGODB_URI=
FINNHUB_API_KEY=

RESEARCH_MODEL_PROVIDER=DeepSeek
RESEARCH_MODEL_NAME=deepseek-chat
ENABLE_HOST_PAPER_JOBS=false
```

Important configuration details:

- Use the **same database password** in `POSTGRES_PASSWORD` and `DATABASE_URL`. The hexadecimal password generated above is suitable for direct use in the URL.
- `5433` is the database port on your computer; Docker maps it to PostgreSQL's internal port `5432`.
- Keep `APP_ENCRYPTION_KEY` stable. Changing it prevents previously saved model keys from being decrypted. Changing `JWT_SECRET` invalidates existing login tokens.
- Keep your existing secrets when restarting or upgrading. `.env` is ignored by Git.
- Leave `MONGODB_URI` empty for this installation. The startup commands also explicitly disable MongoDB, even if you already have a MongoDB container running.
- Yahoo historical daily bars require no API key. For Watchlist quotes, Scanner, and Analyze evidence, save a Finnhub key in Settings → API Keys → Finnhub API. These user-owned workflows use the acting user's saved key and do not fall back to a Finnhub key in `.env`; environment keys remain available to standalone CLI tools. Missing keys or insufficient permissions leave the affected evidence unavailable.
- You do not need a Financial Datasets key for the default data path. Paid model key placeholders elsewhere in `.env.example` are for legacy CLI or explicit integrations; the web analysis uses keys saved in Settings.

## 4. Start PostgreSQL and initialize the database

With Docker running, execute from the repository root:

```bash
docker compose -f compose.local.yml up -d --wait postgres
docker compose -f compose.local.yml ps
```

Wait for PostgreSQL to be healthy, then initialize the application tables:

```bash
MONGODB_URI='' poetry run python -c 'from dotenv import load_dotenv; load_dotenv(); from docker.db_init import main; main()'
```

For a new database, the initializer creates the ORM tables and records the current Alembic version. For an existing versioned database, it applies incremental migrations. Use this initializer for a fresh installation: the legacy Alembic history is not a complete empty-database bootstrap.

Successful initialization ends with:

```text
[db_init] done
```

PostgreSQL stores accounts, password hashes, encrypted model keys, watchlists, configurations, analysis templates, schedules, SQL report copies, and backtest strategies/results. Data lives in the Compose `postgres_data` named volume and persists when the container stops.

**An empty MongoDB is not an error. An unavailable PostgreSQL is an error**, because PostgreSQL stores the application data needed for login and normal use.

## 5. Start the backend

Keep this terminal open:

```bash
MONGODB_URI='' poetry run python -m uvicorn app.backend.main:app \
  --env-file .env --host 127.0.0.1 --port 8001
```

`--env-file .env` loads your configuration before the application is imported. The empty `MONGODB_URI` supplied on the command line takes precedence over the file.

Use a single backend process for this local setup; scheduled jobs currently use an in-process scheduler.

In another terminal, check the backend:

```bash
curl --fail http://127.0.0.1:8001/health
```

Expected response:

```json
{"status":"ok"}
```

Interactive API documentation: [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).

## 6. Start the frontend and create an account

In a new terminal, navigate to your repository root, then run:

```bash
cd app/frontend
npm ci
VITE_API_URL=/api npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173).

1. Register with your own email address and password.
2. Sign in to the account you created.
3. Open Settings to configure model access when you are ready to run AI analysis.

There is **no default administrator account or shared password**. With `REQUIRE_EMAIL_VERIFICATION=false`, local registration does not require email verification or a configured email service. An unconfigured mail service may log a delivery failure without preventing registration.

Keep using `127.0.0.1` consistently in this setup. The `/api` value tells Vite to proxy requests to the backend on port `8001`, so browser requests use the frontend origin. Do not omit `VITE_API_URL`; older services have different fallback addresses.

## 7. Configure AI analysis

Choose one of these options.

### Option A: Use your own provider API key

The default configuration is:

```dotenv
RESEARCH_MODEL_PROVIDER=DeepSeek
RESEARCH_MODEL_NAME=deepseek-chat
```

Save your own DeepSeek key in the application's Settings. Then open Analyze, enter a ticker, select at least one section, and run a small report first. Provider usage may be billed to the key you supplied.

To use another supported provider, update both the provider and model name in `.env`, restart the backend, and save that provider's key in Settings. User analyses and scheduled reports do not automatically consume paid model keys from the host environment.

### Option B: Use a local Ollama model

Install and start Ollama, download a suitable model, and inspect your installed tags:

```bash
ollama list
```

Then update `.env`:

```dotenv
RESEARCH_MODEL_PROVIDER=Ollama
RESEARCH_MODEL_NAME=YOUR_INSTALLED_MODEL_TAG
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Replace `YOUR_INSTALLED_MODEL_TAG` with the exact tag shown by `ollama list`, then restart the backend. The model must support the structured output required by analysis. An unavailable Ollama model does not automatically fall back to a paid provider.

The Debate node supports 1–5 rounds, with a default of 1. Two speakers are selected from Buffett, Lynch, Wood, Burry, and Druckenmiller. Debate uses `2 × rounds + 1` model calls, in addition to routing and other report sections.

## 8. Check your installation

| Check | Expected result |
| --- | --- |
| Backend health | `/health` returns `{"status":"ok"}` |
| Account | Registration and sign-in work |
| Persistence | A saved watchlist remains after a page refresh |
| Backtest | A small watchlist and saved historical date range produce results and charts |
| AI analysis | A configured model can run a small report; missing evidence is identified |
| Paper | The sidebar shows “In development” with no trading controls |

Start with a small watchlist to keep market-data downloads manageable. A successful health check confirms the server is running; it does not verify external data permissions or AI report quality.

An optional developer smoke test checks the no-MongoDB data path without model calls:

```bash
# Run from the repository root.
MONGODB_URI='' poetry run python -m scripts.smoke_no_mongo
```

This script deliberately uses an isolated temporary SQLite database for testing and requests a small amount of online Yahoo data. It does not replace the application's PostgreSQL database or validate full AI reports.

## Daily startup and shutdown

After the first installation, keep your existing `.env` and database volume. Start Docker, then run:

```bash
# Terminal 1: repository root.
docker compose -f compose.local.yml up -d --wait postgres
MONGODB_URI='' poetry run python -m uvicorn app.backend.main:app \
  --env-file .env --host 127.0.0.1 --port 8001
```

```bash
# Terminal 2: repository root, then frontend directory.
cd app/frontend
VITE_API_URL=/api npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

You do not need to reinstall dependencies every time. Stop each application terminal with `Ctrl+C`. To stop the database while retaining its data:

```bash
docker compose -f compose.local.yml stop postgres
```

Do not use `down -v` for routine shutdown: it deletes the database volume.

## Run with one application server

For everyday use, you can build the frontend and let FastAPI serve it, eliminating the separate Vite process:

```bash
# From the repository root.
cd app/frontend
VITE_API_URL=http://127.0.0.1:8001 npm run build
cd ../..
```

Stop any existing backend process, then start it again using the command in step 5. Open [http://127.0.0.1:8001](http://127.0.0.1:8001) and stop Vite. PostgreSQL must remain running.

The API address is embedded **at build time**. Rebuild the frontend after changing that address. The development `/api` proxy belongs to Vite; use the absolute backend address above for this backend-served build.

## Back up and update an existing installation

Stop the application processes while leaving PostgreSQL running. Back up the database before applying migrations:

```bash
# Repository root.
mkdir -p outputs/local-backups
docker compose -f compose.local.yml exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "outputs/local-backups/postgres-$(date +%Y%m%d-%H%M%S).dump"
```

Keep your original encryption key separately with your local configuration. A database backup alone does not recover encrypted model keys without `APP_ENCRYPTION_KEY`.

Save any local source changes before pulling, then update:

```bash
git pull --ff-only origin main
poetry install
MONGODB_URI='' poetry run python -c 'from dotenv import load_dotenv; load_dotenv(); from docker.db_init import main; main()'
cd app/frontend
npm ci
cd ../..
```

Restart the backend and Vite, or rebuild the frontend for the backend-served setup. Do not overwrite your `.env` or regenerate existing secrets.

The current migrations include debate rounds, personal Paper prototype tables, and `report_schedules.analysis_config` for scheduled workflow snapshots. Old schedules retain their default behavior. Old backtest records are retained and must be rerun to use the corrected execution and cost calculations.

An older SQLite database is not automatically imported into PostgreSQL. An existing business database without Alembic version history needs a separate schema/migration review before using the initializer.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| `poetry`, Python, or Node is not found | Reopen the terminal and check PATH. Select the installed Python with `poetry env use`. |
| Docker connection fails | Start Docker Desktop or your Docker engine, then retry `docker info`. |
| PostgreSQL fails to start | Check `docker compose -f compose.local.yml ps` and `docker compose -f compose.local.yml logs postgres`; ensure host port `5433` is free. |
| Database authentication fails | Match the password in `POSTGRES_PASSWORD` and `DATABASE_URL`. Changing `.env` does not change the password in an already initialized database volume. |
| A database column is missing after updating | Stop the app, back up PostgreSQL, and run the initializer to apply migrations. |
| The page loads but requests fail | Confirm the backend is on `8001` and Vite started with `VITE_API_URL=/api`. For a static build, rebuild with the correct absolute backend URL. |
| Frontend port `5173` is occupied | Stop the old project frontend. If you change ports, update `FRONTEND_ORIGINS` in `.env` and restart the backend. |
| Analyze says a model key is missing | Save the configured provider's key in Settings, or verify the Ollama service and model tag. |
| Current quotes or other evidence are missing | Check Finnhub configuration, internet access, and provider permissions. Yahoo daily bars do not supply every evidence type. |
| Saved model keys cannot be decrypted | Restore the original `APP_ENCRYPTION_KEY`, or save the keys again in Settings. |

## Current feature status

| Area | Available | Current limits |
| --- | --- | --- |
| Watchlist / Screener / Scanner | Watchlists, screening, event scans | Online data and provider permissions required; snapshot refresh requires login |
| Analyze / Reports | Predefined analysis sections, personas, debate, saved templates, scheduled configuration snapshots | Canvas edges do not define arbitrary execution graphs; at least one valid section is required |
| Backtest | Historical rule strategies, costs, IS/OOS metrics and charts | Basic version; no Analyze strategy integration, progress display, cancellation, or parameter comparison |
| Paper | Prototype code and stored records retained | **In development; unavailable to users.** No automatic market-price valuation |

Backtests evaluate signals at the close and execute at the next available trading day's open. Trade P&L includes entry and exit costs; the OOS benchmark uses the OOS evaluation window. Analyze and Backtest currently operate independently.

When enabled, MongoDB provides additional cache/history storage, datasets, node caches, and checkpoints. Without it, online analysis continues, but SQL report copies do not replace full MongoDB history or checkpoint-based recovery.

## Scanner daily-bar detectors

Scanner configurations now offer three additional detectors. Open the Scanner configuration dialog and enable them in the detector list. Existing configurations with an explicit detector selection keep that selection; configurations using all detectors include the new ones.

| Detector | Default condition | Data |
| --- | --- | --- |
| Relative Volume | Latest volume ≥2× the mean of the preceding 20 bars, excluding the latest bar. Direction follows the daily close-to-close return. | Yahoo daily volume and adjusted closes |
| 20-Day Closing Breakout | Latest adjusted close strictly above or below the preceding 20 closing prices. A tie does not trigger. | Yahoo adjusted closes |
| Relative Strength vs SPY | 20-session return exceeds or trails SPY by at least 5 percentage points, using matching dates. | Yahoo adjusted closes for the stock and SPY |

These detectors work without a Finnhub key or MongoDB. MongoDB remains an optional cache/history layer. Missing or insufficient bars produce a no-data outcome; relative strength also requires matching SPY sessions. During market hours, the latest daily bar can still change and its volume is incomplete; use an after-close scan for daily results.

Each qualifying day can trigger again. These rules do not yet implement first-hit alerts, cooldowns, or AND/OR combinations. The dialog's severity multiplier controls ranking, not the trigger threshold; custom window/threshold parameters currently exist only in the Python detector constructors. Breakouts have fixed signed severity 2; relative-volume severity is capped at 5× (zero directional severity for a flat close); relative strength uses 2 severity units per 5-point spread, capped at 5. These scales are ranking heuristics, not probabilities or statistical z-scores. Relative strength describes performance against SPY and can be bullish even when both prices fell.

## Roadmap: connect screening, scanning, research, and backtesting

The stages below are **planned work**, not a description of an already integrated product. Existing modules provide parts of this workflow, but the end-to-end links and shared rule definitions still need implementation. No delivery dates are committed.

Target workflow:

```text
Screener → saved stock universe → Scanner signal configuration
                                      ├→ Backtest with explicit trading rules
                                      └→ Scan hits → user-selected Analyze → linked report
```

| Stage | Planned work | Completion criteria |
| --- | --- | --- |
| 1. Share stock universes | Save selected Screener results to a Watchlist and use that list to create a Scanner configuration. Freeze the selected tickers first; dynamic re-screening comes later. | The user can trace a scan's exact ticker universe back to its saved selection. |
| 2. Carry scan evidence into Analyze | Pass the triggering scan ID, timestamp, detector values, and evidence alongside the ticker. Keep scan-time observations separate from data fetched for analysis. | The report explains why analysis was started and links back to the triggering scan. |
| 3. Link reports back to results | Show the latest report, its timestamp, and triggering signal on Scanner results and Watchlist rows. | Users can open the relevant report and see whether newer signals have arrived since it was generated. |
| 4. Validate Scanner rules with Backtest | Share supported detector definitions between scanning and backtesting. Ask users to specify entry/exit timing, holding limits, sizing, and costs before running. | A supported rule has matching signal semantics in historical and current-data execution; the saved result contains its rule version, universe, parameters, and data window. |
| 5. Use historical results in research | Link the appropriate backtest results to Analyze as evidence; offer rule-based section templates for different scan triggers. | Reports identify the tested rule, sample size, IS/OOS periods, costs, and limitations instead of treating backtest performance as a promise. |
| 6. Add advanced workflows | Consider dynamic Screener universes, historical event studies, parameter comparison, and translating Analyze suggestions into user-reviewed strategy rules. | Each workflow preserves its configuration and evidence, makes model costs visible, and can be reproduced before automation is expanded. |

Implementation principles:

- Keep analysis user-triggered initially. Add batch or automatic model execution only with explicit scope and usage controls.
- A detector signal is not a complete trading strategy. Backtest must collect the missing trade rules rather than silently inventing them.
- Reusing today's selected stocks for past periods is a **current-universe historical test**, not a point-in-time Screener strategy backtest. Label selection/survivorship bias; historical universe and publication-time data are required for stronger claims.
- Use only data actually available from the configured providers or MongoDB history. Stored history cannot supply missing historical constituents, filings, or timestamps that were never collected.
- Paper remains under development and closed to users. Reopening it is a separate decision after market-price valuation and execution behavior are defined and tested.

## Further documentation

- [Detailed local deployment guide (Chinese)](docs/LOCAL_DEPLOY.md)
- [Development and validation](docs/development.md)
- [Deployment notes](docs/DEPLOY.md)
- [Requirements](docs/requirements/market-data-and-analyze.md)
- [MongoDB data model](docs/design/mongodb-market-data-erd.md)
- [Current handoff](docs/handoffs/2026-10-28-postgres-local.md)
- [Code review and fixes](docs/reviews/2026-10-29-main-review.md)
- [Documentation index](docs/README.md)

Research output is intended for analysis and does not promise investment returns.
