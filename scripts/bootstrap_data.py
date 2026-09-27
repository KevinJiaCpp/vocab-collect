"""Download optional lexical datasets and index OEWN terms for search.

Safe to rerun. Network failures leave the rest of the application intact.
"""

from __future__ import annotations

import sys
import hashlib
from pathlib import Path
from urllib.request import urlopen

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.dictionary_service import normalize_dictionary_term, normalize_word  # noqa: E402
from app.models import DictionaryTerm  # noqa: E402

CMUDICT_REVISION = "74790861f652b15e4ac49015a90074ad62a27690"
CMUDICT_SHA256 = "81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22"


def download(url: str) -> bytes:
    with urlopen(url, timeout=60) as response:
        return response.read()


def install_cmudict() -> None:
    if settings.cmudict_path.exists():
        checksum = hashlib.sha256(settings.cmudict_path.read_bytes()).hexdigest()
        if checksum != CMUDICT_SHA256:
            raise ValueError("Installed CMUdict checksum does not match the pinned release")
        return
    source = f"https://raw.githubusercontent.com/cmusphinx/cmudict/{CMUDICT_REVISION}/cmudict.dict"
    payload = download(source)
    if hashlib.sha256(payload).hexdigest() != CMUDICT_SHA256:
        raise ValueError("Downloaded CMUdict checksum does not match the pinned release")
    settings.cmudict_path.parent.mkdir(parents=True, exist_ok=True)
    settings.cmudict_path.write_bytes(payload)
    print(f"Installed CMUdict: {len(payload)} bytes")


def install_licenses() -> None:
    license_dir = ROOT / "licenses"
    license_dir.mkdir(exist_ok=True)
    sources = {
        "CMUDICT.txt": f"https://raw.githubusercontent.com/cmusphinx/cmudict/{CMUDICT_REVISION}/LICENSE",
        "OEWN.txt": "https://raw.githubusercontent.com/globalwordnet/english-wordnet/main/LICENSE.md",
        "WNDB.txt": "https://raw.githubusercontent.com/globalwordnet/english-wordnet/main/WNDB_License.txt",
    }
    for name, url in sources.items():
        path = license_dir / name
        if not path.exists():
            path.write_bytes(download(url))
    print("Dataset license texts ready")


def install_wordnet() -> None:
    import wn

    wn.config.data_directory = settings.wn_dir
    try:
        wordnet = wn.Wordnet(settings.lexicon)
        words = wordnet.words()
        print(f"Using {settings.lexicon}")
    except Exception:
        print(f"Downloading {settings.lexicon} …")
        wn.download(settings.lexicon)
        wordnet = wn.Wordnet(settings.lexicon)
        words = wordnet.words()
    with SessionLocal() as db:
        existing = set(db.scalars(select(DictionaryTerm.normalized_term)).all())
        count = 0
        for word in words:
            lemma = word.lemma().replace("_", " ")
            key = normalize_dictionary_term(lemma)
            if key and key not in existing:
                db.add(DictionaryTerm(term=lemma, normalized_term=key, search_term=normalize_word(lemma)))
                existing.add(key)
                count += 1
                if count % 1000 == 0:
                    db.commit()
        db.commit()
    print(f"Indexed {count} dictionary terms")


def install_morphology() -> None:
    from morphoneme import MP

    MP()
    print("Morphology data ready")


if __name__ == "__main__":
    failures = 0
    for operation in (install_cmudict, install_wordnet, install_morphology, install_licenses):
        try:
            operation()
        except Exception as exc:
            failures += 1
            print(f"{operation.__name__} failed: {exc}", file=sys.stderr)
    raise SystemExit(1 if failures else 0)
