# Vocab Collect

Vocab Collect is a self-hosted English vocabulary trainer with spaced repetition, bidirectional cards, ordered word lists, WordNet dictionary data, morphology, pronunciation, and per-user progress.

## Quick start (Windows)

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

Then open `http://127.0.0.1:8000`.

The launcher reserves the port before starting the application and returns an error if it is already occupied. On Ctrl+C, unfinished requests have up to five seconds to finish before they are cancelled.

The setup script creates `.venv`, installs the backend and frontend dependencies, applies database migrations, downloads the optional linguistic datasets, and builds the React application. The app remains usable when an optional data download is unavailable; affected dictionary features display an actionable unavailable state.

## Development

Run the backend:

```powershell
.\scripts\run.ps1 -Reload
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

Configure a language model under **Settings → LLM** with an OpenAI-compatible API base URL, model ID, and optional API key. Settings belong to your account and are stored on this server. Keys are stored in the server database; the API returns only whether a key is saved. Leaving the key field blank preserves it, and **Remove saved key** clears it when you save.

In the Dictionary, select **Examples** beside a sense to generate three sentences with your configured model. The backend sends the word, part of speech, and that sense's definition to your configured service using the [Chat Completions API](https://developers.openai.com/api/reference/resources/chat/methods/create). Generated sentences are labeled separately from dictionary examples and cached per account on this server. They return when you revisit the word or refresh. **Regenerate** replaces a sense's cached sentences after successful generation; **Clear** removes only its generated sentences. Cached sentences are matched by word, part of speech, and definition, so reordered senses keep their examples and changed definitions do not inherit old examples.

## Data and licenses

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Dictionary definitions come from Open English WordNet 2025+, pronunciation entries from CMUdict, morphology from Morphōneme, and requested audio from Wikimedia projects with per-file attribution.

