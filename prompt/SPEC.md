# Vocabulary App - *Vocab Collect*
## Requirements
- Use Python + FastAPI for backend.
- Use TypeScript + React + VITE for frontend.
- Use adaptive layout to make the UI look native on both laptops and mobile devices.
- Use Python virtual environment.
- Use SQLite for database.
- Support multiple users with authentication.
- Fulfill license requirements of all third party dependencies.

## Logic
### Cards
- We should use py-fsrs library for spaced repetition.
- Seperate cards should be created for word-to-meaning recall and meaning-to-word recall.
- Review logs should capture all information needed to use the py-fsrs optimizer.
- Optimizer should not be used until sufficient data of an user is recorded.
### Word Lists
- Inherent property of a word list (should be preserved when exported): name, words, order, direction (w2m, m2w, bi-dir)
- Operations available to a word list: activate, deactivate, import, export, shuffle, add entry, remove entry, create, delete, rename
- Support multiple active word lists.
- A word list itself contains only textual words, with no underlying data assoiciated with it; instead, users' progress on each word should be stored in a table irrelavent to the word lists.
### Dictionary
- Use wn library to interface with wordnet. Use the lexicon "oewn:2025+" for senses, synonyms, antonyms, and derivatives.
- Use morphoneme for decomposition (prefixes, roots, suffixes).
- Use CMUdict for IPA, and when user requests, obtain audio from Wiktionary.
- Support a modern search mechanism with prefix search and fuzzy search.
- In the dictionary entry page of a word, allow the user to add the word to a word list or attach a note to the word.
### Learning/Review Sessions
- Allow the user to configure how many words to review in a batch, and how many words to learn in a batch.
- All learning or review should be reported to py-fsrs and recorded in the LOG table for future optimization.
- In learning sessions, load more words into the pool than the batch size (default 1.5 times the batch size). Use a queue system to schedule the words, ignore the interval suggested by the py-fsrs scheduler. Set the learning step to 4. When enough words are moved to review by py-fsrs, end the session. Prompt the user to review first before learning if they do not do so.
- In review mode, display each word once and ask the user to recall. Certain words may get transferred to relearn. Those words should be injected into the learning session.
- A button can be used to toggle to "meaning to word" recall mode. Apply the same logic above, but only include words with "word to meaning" card in review state.
- In both sessions, allow the user to specify that they are familiar with the word and will not study it in any forms in the future. Or the user can specify that the word is useless for them, which gives the same effect.

## UI
- Four tabs: Home, Dashboard, Collection, and Dictionary.
- Collection tab is where the user manage: all their word lists, all their learned words, and all their notes.
