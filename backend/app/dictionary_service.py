from __future__ import annotations

import html
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from threading import RLock, local
from typing import Any

import httpx
from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AudioCache, DictionaryTerm

logger = logging.getLogger(__name__)

def normalize_word(value: str) -> str:
    return normalize_dictionary_term(value).casefold()


def normalize_dictionary_term(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.strip().split())


def example_mentions_term(example: str, term: str) -> bool:
    """WordNet stores examples on the synset, so they illustrate whichever lemma the submitter had
    in mind; keep only the ones that actually use the looked-up term."""
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", example, re.IGNORECASE) is not None


ARPABET: dict[str, str] = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "EH": "ɛ", "ER": "ɝ", "EY": "eɪ",
    "F": "f", "G": "ɡ", "HH": "h", "IH": "ɪ", "IY": "i", "JH": "dʒ", "K": "k",
    "L": "l", "M": "m", "N": "n", "NG": "ŋ", "OW": "oʊ", "OY": "ɔɪ", "P": "p",
    "R": "r", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "UH": "ʊ", "UW": "u",
    "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}


def arpabet_to_ipa(phones: list[str]) -> str:
    pieces: list[str] = []
    primary_added = False
    consonants: list[str] = []
    for phone in phones:
        match = re.fullmatch(r"([A-Z]+)([012]?)", phone)
        if not match:
            continue
        symbol, stress = match.groups()
        ipa = ARPABET.get(symbol, symbol.lower())
        if stress:
            if consonants:
                pieces.extend(consonants[:-1] if pieces else [])
                consonants = consonants[-1:] if pieces else consonants
            if stress == "1" and not primary_added:
                pieces.append("ˈ")
                primary_added = True
            elif stress == "2":
                pieces.append("ˌ")
            pieces.extend(consonants)
            consonants = []
            pieces.append(ipa)
        else:
            consonants.append(ipa)
    pieces.extend(consonants)
    return f"/{''.join(pieces)}/"


@lru_cache(maxsize=1)
def _cmudict() -> dict[str, list[list[str]]]:
    result: dict[str, list[list[str]]] = {}
    path = settings.cmudict_path
    if not path.exists():
        return result
    for line in path.read_text(encoding="latin-1").splitlines():
        if not line or line.startswith(";;; ") or " " not in line:
            continue
        key, phones = line.split(None, 1)
        key = re.sub(r"\(\d+\)$", "", key).casefold()
        result.setdefault(key, []).append(phones.split())
    return result


class DictionaryService:
    def __init__(self) -> None:
        self._local = local()
        self._wordnet_lock = RLock()

    def _get_wordnet(self) -> Any | None:
        wordnet = getattr(self._local, "wordnet", None)
        if wordnet is False:
            return None
        if wordnet is None:
            try:
                import wn

                wn.config.data_directory = settings.wn_dir
                wn.config.allow_multithreading = True
                wordnet = wn.Wordnet(settings.lexicon)
                self._local.wordnet = wordnet
            except Exception:
                self._local.wordnet = False
                return None
        return wordnet

    def _get_morph(self) -> Any | None:
        morph = getattr(self._local, "morph", None)
        if morph is False:
            return None
        if morph is None:
            try:
                from morphoneme import MP

                morph = MP()
                self._local.morph = morph
            except Exception:
                self._local.morph = False
                return None
        return morph

    def lookup(self, word: str) -> dict[str, Any] | None:
        display_key = normalize_dictionary_term(word)
        key = display_key.casefold()
        senses = self._lookup_senses(display_key)
        if not senses:
            return None

        pronunciations = [arpabet_to_ipa(item) for item in _cmudict().get(key, [])]
        morphology: dict[str, Any] | None = None
        morph = self._get_morph()
        if morph is not None:
            try:
                morphology = morph.word_morph(key)
            except Exception:
                morphology = None
        return {
            "word": display_key,
            "normalized_word": key,
            "senses": senses,
            "pronunciations": pronunciations,
            "morphology": morphology,
            "attribution": "Definitions: Open English WordNet 2025+ (Princeton WordNet / OEWN, CC BY 4.0)",
        }

    def available(self) -> bool:
        with self._wordnet_lock:
            return self._get_wordnet() is not None

    def _lookup_senses(self, key: str) -> list[dict[str, Any]]:
        senses: list[dict[str, Any]] = []
        with self._wordnet_lock:
            wordnet = self._get_wordnet()
            if wordnet is None:
                return senses
            try:
                for synset in wordnet.synsets(key.replace(" ", "_")):
                    lemmas = [str(value).replace("_", " ") for value in synset.lemmas()]
                    if key not in {normalize_dictionary_term(lemma) for lemma in lemmas}:
                        continue
                    definition = synset.definition() or ""
                    examples = [item for item in synset.examples() or [] if example_mentions_term(item, key)]
                    antonyms: list[str] = []
                    derivatives: list[str] = []
                    for sense in synset.senses():
                        if normalize_dictionary_term(sense.word().lemma().replace("_", " ")) != key:
                            continue
                        for relation_name, related in sense.relations().items():
                            # OEWN keeps one entry per part of speech, so relations can point back at the same
                            # spelling ("retro a." derives from "retro n."), which reads as noise in the UI.
                            related_lemmas = [lemma for lemma in (item.word().lemma().replace("_", " ") for item in related) if normalize_dictionary_term(lemma) != key]
                            if relation_name == "antonym":
                                antonyms.extend(related_lemmas)
                            elif relation_name == "derivation":
                                derivatives.extend(related_lemmas)
                    senses.append({
                        "part_of_speech": {"n": "noun", "v": "verb", "a": "adjective", "s": "adjective", "r": "adverb"}.get(str(synset.pos), str(synset.pos)),
                        "definition": definition,
                        "examples": examples,
                        "synonyms": [lemma for lemma in lemmas if normalize_dictionary_term(lemma) != key],
                        "antonyms": sorted(set(antonyms)),
                        "derivatives": sorted(set(derivatives)),
                    })
            except Exception:
                logger.exception("OEWN lookup failed for %s", key)
                senses = []
        return senses

    def has_definition(self, db: Session, word: str) -> bool:
        key = normalize_dictionary_term(word)
        return db.scalar(select(DictionaryTerm.id).where(DictionaryTerm.normalized_term == key)) is not None or self.lookup(word) is not None

    def search(
        self,
        db: Session,
        query: str,
        page: int = 1,
        page_size: int = 20,
        exclude_multiword_expressions: bool = False,
    ) -> dict[str, Any]:
        exact_key = normalize_dictionary_term(query)
        search_key = exact_key.casefold()
        if not search_key:
            return {"items": [], "page": page, "has_more": False}
        term_filter = DictionaryTerm.search_term.not_like("% %") if exclude_multiword_expressions else True
        exact = list(db.scalars(select(DictionaryTerm.term).where(DictionaryTerm.normalized_term == exact_key, term_filter)).all())
        case_variants = list(db.scalars(select(DictionaryTerm.term).where(
            DictionaryTerm.search_term == search_key,
            DictionaryTerm.normalized_term != exact_key,
            term_filter,
        ).order_by(DictionaryTerm.normalized_term)).all())
        prefix = list(db.scalars(select(DictionaryTerm.term).where(
            DictionaryTerm.search_term.startswith(search_key, autoescape=True),
            DictionaryTerm.search_term != search_key,
            term_filter,
        ).order_by(DictionaryTerm.search_term, DictionaryTerm.normalized_term).limit(page * page_size + 1)).all())
        candidates = exact + case_variants + prefix
        if len(candidates) < page * page_size:
            all_terms = [row[0] for row in db.execute(select(DictionaryTerm.term).where(term_filter)).all()]
            fuzzy = [value for value, score, _ in process.extract(search_key, all_terms, scorer=fuzz.WRatio, processor=normalize_word, limit=80) if score >= 62 and value not in candidates]
            candidates.extend(fuzzy)
        start = (page - 1) * page_size
        items = candidates[start:start + page_size]
        return {"items": [{"word": item, "match": "exact" if normalize_dictionary_term(item) == exact_key else "case variant" if normalize_word(item) == search_key else "prefix" if normalize_word(item).startswith(search_key) else "fuzzy"} for item in items], "page": page, "has_more": len(candidates) > start + page_size}


dictionary_service = DictionaryService()


def _strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return html.unescape(text).strip()


async def resolve_audio(db: Session, word: str) -> dict[str, Any]:
    key = normalize_word(word)
    cached = db.get(AudioCache, key)
    now = datetime.now(timezone.utc)
    if cached:
        fetched = cached.fetched_at.replace(tzinfo=timezone.utc) if cached.fetched_at.tzinfo is None else cached.fetched_at
        if now - fetched < timedelta(days=7):
            return json.loads(cached.payload_json)

    headers = {"User-Agent": "VocabCollect/0.1 (self-hosted vocabulary application)"}
    async with httpx.AsyncClient(timeout=10, headers=headers, follow_redirects=True) as client:
        try:
            wiki = await client.get("https://en.wiktionary.org/w/api.php", params={
                "action": "query", "format": "json", "prop": "images", "titles": key, "imlimit": "max", "origin": "*",
            })
            wiki.raise_for_status()
            pages = wiki.json().get("query", {}).get("pages", {})
            images = next(iter(pages.values()), {}).get("images", [])
            titles = [item.get("title", "") for item in images if item.get("title", "").casefold().endswith((".ogg", ".oga", ".wav", ".mp3"))]
            if not titles:
                raise LookupError("No pronunciation audio was found")
            commons = await client.get("https://commons.wikimedia.org/w/api.php", params={
                "action": "query", "format": "json", "prop": "imageinfo", "titles": titles[0],
                "iiprop": "url|extmetadata", "origin": "*",
            })
            commons.raise_for_status()
            page = next(iter(commons.json().get("query", {}).get("pages", {}).values()), {})
            info = (page.get("imageinfo") or [{}])[0]
            metadata = info.get("extmetadata") or {}
            payload = {
                "url": info.get("url"),
                "source_url": info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{titles[0].replace(' ', '_')}",
                "title": titles[0].removeprefix("File:"),
                "creator": _strip_html((metadata.get("Artist") or {}).get("value")) or "Wikimedia contributor",
                "license": _strip_html((metadata.get("LicenseShortName") or {}).get("value")) or "See source",
                "attribution": _strip_html((metadata.get("Credit") or {}).get("value")),
            }
            if not payload["url"]:
                raise LookupError("Audio metadata did not contain a playable URL")
        except httpx.HTTPError as exc:
            if cached:
                return json.loads(cached.payload_json)
            raise LookupError("Audio is unavailable while offline. Try again when connected.") from exc
        except (LookupError, ValueError) as exc:
            if cached:
                return json.loads(cached.payload_json)
            raise LookupError(str(exc)) from exc
    if cached is None:
        cached = AudioCache(normalized_word=key, payload_json=json.dumps(payload), fetched_at=now)
        db.add(cached)
    else:
        cached.payload_json = json.dumps(payload)
        cached.fetched_at = now
    db.commit()
    return payload
