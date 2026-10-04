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

Under **Settings → Appearance**, choose System, Light, or Dark and an accent color: Blue, Teal, Green, Violet, Rose, or Orange. The two choices are independent, apply immediately, and are saved in the current browser. Accent colors adapt to light and dark themes.

Configure a language model under **Settings → LLM** with an OpenAI-compatible API base URL, model ID, and optional API key. Settings belong to your account and are stored on this server. Keys are stored in the server database; the API returns only whether a key is saved. Leaving the key field blank preserves it, and **Remove saved key** clears it when you save.

In the Dictionary, select **Examples** beside a sense to generate three sentences with your configured model. The backend sends the word, part of speech, and that sense's definition to your configured service using the [Chat Completions API](https://developers.openai.com/api/reference/resources/chat/methods/create). Generated sentences are labeled separately from dictionary examples and cached per account on this server. They return when you revisit the word or refresh. **Regenerate** replaces a sense's cached sentences after successful generation; **Clear** removes only its generated sentences. Cached sentences are matched by word, part of speech, and definition, so reordered senses keep their examples and changed definitions do not inherit old examples.

## Word lists and notes

A note belongs to one word list and inherits that list's account ownership. It can explain several words in that list, and each word can have several notes. Editing a shared note updates the explanation for every attached word. Removing a word removes its note attachments; the notes remain in the list, including when they have no attached words, so they can be relinked later. Deleting a list deletes its notes.

Dictionary entries show notes from all of your lists, including paused lists. Learning and review cards show notes from active lists after revealing the answer. Collection → Notes lets you manage notes by list, including notes with no linked words.

Word lists use UTF-8 JSON for both import and export. Version 2 stores each shared note once and references its words by spelling:

```json
{
  "version": 2,
  "name": "Clear explanations",
  "direction": "bidirectional",
  "words": ["Lucid", "Resilient"],
  "notes": [
    {"body": "Both adjectives can describe a person.", "words": ["Lucid", "Resilient"]},
    {"body": "Clear and easy to understand.", "words": ["Lucid"]},
    {"body": "An explanation to attach later.", "words": []}
  ]
}
```

Word order is preserved. Words must be unique after case and spacing normalization, and every note reference must identify a word in the same file. An invalid import creates no list or notes. Version 1 JSON files containing words remain importable; new exports use version 2. TXT import and export have been removed.

Before upgrading an existing installation, stop the server and back up its database. Migration `0006_list_notes` copies each former per-word note into every owned list containing that word, including paused lists. Notes without any list membership are preserved with their words in an inactive **Imported notes** recovery list; an available numbered name is used if that name already exists. Original note text and timestamps are retained.

## Data and licenses

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Dictionary definitions come from Open English WordNet 2025+, pronunciation entries from CMUdict, morphology from Morphōneme, and requested audio from Wikimedia projects with per-file attribution.

