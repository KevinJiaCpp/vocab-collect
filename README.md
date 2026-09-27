# Vocab Collect

Vocab Collect is a self-hosted English vocabulary trainer with spaced repetition, bidirectional cards, ordered word lists, WordNet dictionary data, morphology, pronunciation, and per-user progress.

## Quick start (Windows)

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

Then open `http://127.0.0.1:8000`.

The setup script creates `.venv`, installs the backend and frontend dependencies, applies database migrations, downloads the optional linguistic datasets, and builds the React application. The app remains usable when an optional data download is unavailable; affected dictionary features display an actionable unavailable state.

## Development

Run the backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend
```

Run the frontend in another terminal:

```powershell
cd frontend
npm run dev
```

Vite proxies `/api` to FastAPI. Production builds are served by FastAPI from `frontend/dist`.

## Configuration

Copy `.env.example` to `.env` when you need to override defaults.

- `VOCAB_DATA_DIR`: application data directory; defaults to `./data`.
- `VOCAB_DATABASE_URL`: SQLAlchemy database URL; defaults to SQLite in the data directory.
- `VOCAB_SECURE_COOKIES`: set to `true` behind HTTPS.
- `VOCAB_ALLOWED_ORIGINS`: comma-separated origins accepted for state-changing requests.

## Data and licenses

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Dictionary definitions come from Open English WordNet 2025+, pronunciation entries from CMUdict, morphology from Morphōneme, and requested audio from Wikimedia projects with per-file attribution.

