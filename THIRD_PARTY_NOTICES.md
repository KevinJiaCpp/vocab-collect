# Third-party notices

Vocab Collect uses open-source software and openly licensed linguistic datasets. The dependency lockfiles contain the exact installed versions. Copyright remains with each project and contributor.

## Linguistic data

- **Open English WordNet 2025+** — derived from Princeton WordNet and further developed under Creative Commons Attribution 4.0. Vocab Collect displays and redistributes definitions with attribution to Princeton WordNet and the Open English WordNet team. Source: https://github.com/globalwordnet/english-wordnet
- **CMU Pronouncing Dictionary** — Copyright 1993–2015 Carnegie Mellon University. The bundled raw dictionary is pinned to revision `74790861f652b15e4ac49015a90074ad62a27690` and SHA-256 `81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22`. Redistribution is permitted with retention of its copyright and disclaimer. Source: https://github.com/cmusphinx/cmudict
- **Morphōneme** — MIT-licensed software. Its morphology database combines umLabeller/UniMorph and CityLex data under their respective terms. Source: https://github.com/connoryang331/morphoneme
- **Wiktionary and Wikimedia Commons audio** — individual files use their own licenses. Vocab Collect fetches and displays the source, creator, and license beside each playable file and does not bundle the audio.

Full OEWN, Princeton WordNet, and CMUdict license texts are retained in `licenses/` when the data bootstrap succeeds and shown on the in-app Licenses screen. Dynamic audio attribution is provided in the interface.

## Principal software dependencies

- FastAPI, Starlette, SQLAlchemy, Alembic, Pydantic, HTTPX, RapidFuzz, Wn, py-fsrs, React, React Router, TanStack Query, Vite, TypeScript, and Lucide React are used under their published licenses.
- Passwords are hashed with Argon2 through `pwdlib`/`argon2-cffi`.

No dependency or data-source name is used to imply endorsement.
