from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.config import settings
from app.dictionary_service import dictionary_service, example_mentions_term, normalize_dictionary_term, normalize_word
from app.main import app
from app.models import AudioCache, ReviewLog


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)

    def test_db():
        with Session(engine) as db:
            yield db

    def lookup(word):
        key = normalize_word(word)
        if key not in {"lucid", "resilient"}:
            return None
        return {
            "word": word, "normalized_word": key,
            "senses": [{"part_of_speech": "adjective", "definition": f"Definition of {key}", "examples": [], "synonyms": [], "antonyms": [], "derivatives": []}],
            "pronunciations": [], "morphology": None, "attribution": "Test dictionary",
        }

    monkeypatch.setattr(dictionary_service, "lookup", lookup)
    app.dependency_overrides[get_db] = test_db
    test_client = TestClient(app)
    yield test_client, engine
    app.dependency_overrides.clear()


def register(client, username):
    response = client.post("/api/auth/register", json={"username": username, "password": "long-enough-password"})
    assert response.status_code == 201, response.text


def test_auth_lists_import_notes_and_isolation(client):
    http, _ = client
    register(http, "StudentA")
    assert http.post("/api/auth/register", json={"username": "studenta", "password": "long-enough-password"}).status_code == 409
    created = http.post("/api/lists", json={"name": "First", "direction": "bidirectional"})
    assert created.status_code == 201
    list_id = created.json()["id"]
    assert http.post(f"/api/lists/{list_id}/entries", json={"word": "  Lucid  "}).status_code == 201
    assert http.post(f"/api/lists/{list_id}/entries", json={"word": "LUCID"}).status_code == 409
    assert http.post(f"/api/lists/{list_id}/entries", json={"word": "unknownwordxyz"}).json()["has_definition"] is False
    exported = http.get(f"/api/lists/{list_id}/export?format=json").json()
    assert exported == {"version": 1, "name": "First", "direction": "bidirectional", "words": ["Lucid", "unknownwordxyz"]}
    imported = http.post("/api/lists/import", files={"file": ("copy.json", json.dumps({**exported, "name": "Copy"}), "application/json")})
    assert imported.status_code == 201, imported.text
    assert [entry["word"] for entry in imported.json()["entries"]] == exported["words"]
    assert http.put("/api/words/lucid/note", json={"body": "A memorable note"}).status_code == 200
    assert http.get("/api/words/lucid/note").json()["body"] == "A memorable note"
    assert http.post("/api/auth/logout").status_code == 204
    assert http.get("/api/lists").status_code == 401
    register(http, "StudentB")
    assert http.get("/api/lists").json() == []
    assert http.get("/api/words/lucid/note").json()["body"] == ""
    assert http.get(f"/api/lists/{list_id}").status_code == 404


def test_study_reveal_idempotency_reverse_unlock_and_resume(client):
    http, engine = client
    register(http, "StudyUser")
    http.put("/api/settings", json={"learn_batch_size": 1, "review_batch_size": 1, "pool_multiplier": 1.5})
    list_id = http.post("/api/lists", json={"name": "Study", "direction": "bidirectional"}).json()["id"]
    http.post(f"/api/lists/{list_id}/entries", json={"word": "Lucid"})
    assert http.get("/api/study/overview").json()["new"] == {"w2m": 1, "m2w": 0}
    session = http.post("/api/study/sessions", json={"kind": "learning", "direction": "w2m"}).json()
    session_id = session["id"]
    prompt = http.get(f"/api/study/sessions/{session_id}/next").json()
    token = prompt["presentation_token"]
    assert prompt["item"]["prompt"] == {"word": "Lucid"}
    assert "answer" not in prompt["item"]
    assert http.post(f"/api/study/sessions/{session_id}/answer", json={"presentation_token": token, "rating": 4}).status_code == 409
    assert http.get("/api/study/overview").json()["active_session"]["id"] == session_id
    revealed = http.post(f"/api/study/sessions/{session_id}/reveal", json={"presentation_token": token}).json()
    assert revealed["item"]["answer"]["senses"][0]["definition"] == "Definition of lucid"
    graded = http.post(f"/api/study/sessions/{session_id}/answer", json={"presentation_token": token, "rating": 4, "duration_ms": 500})
    assert graded.status_code == 200, graded.text
    assert graded.json()["session"]["status"] == "completed"
    assert http.post(f"/api/study/sessions/{session_id}/answer", json={"presentation_token": token, "rating": 4}).json()["duplicate"] is True
    with Session(engine) as db:
        logs = db.scalars(select(ReviewLog)).all()
        assert len(logs) == 1
        assert logs[0].duration_ms == 500
        assert logs[0].before_json and logs[0].after_json and logs[0].fsrs_log_json
    assert http.get("/api/study/overview").json()["new"]["m2w"] == 1
    reverse = http.post("/api/study/sessions", json={"kind": "learning", "direction": "m2w"}).json()
    assert reverse["direction"] == "m2w"
    reverse_prompt = http.get(f"/api/study/sessions/{reverse['id']}/next").json()
    assert "senses" in reverse_prompt["item"]["prompt"]
    assert http.get("/api/study/overview").json()["active_session"]["id"] == reverse["id"]
    skipped = http.post(f"/api/study/sessions/{reverse['id']}/skip", json={"presentation_token": reverse_prompt["presentation_token"], "status": "familiar"})
    assert skipped.json()["status"] == "completed"
    assert http.get("/api/study/overview").json()["new"] == {"w2m": 0, "m2w": 0}


def test_normalization_and_search_rank(client):
    http, engine = client
    assert normalize_word("  ＬＵＣＩＤ  ") == "lucid"
    register(http, "Searcher")
    from app.models import DictionaryTerm
    with Session(engine) as db:
        for term in ("lucid", "lucidity", "lucid dream", "well-being", "resilient", "crane", "Crane"):
            db.add(DictionaryTerm(term=term, normalized_term=normalize_dictionary_term(term), search_term=normalize_word(term)))
        db.commit()
    assert http.get("/api/dictionary/search?q=lucid").json()["items"][0] == {"word": "lucid", "match": "exact"}
    assert http.get("/api/dictionary/search?q=luci").json()["items"][0]["match"] == "prefix"
    assert http.get("/api/dictionary/search?q=lucdi").json()["items"][0]["match"] == "fuzzy"
    crane = http.get("/api/dictionary/search?q=crane").json()["items"]
    assert crane[:2] == [{"word": "crane", "match": "exact"}, {"word": "Crane", "match": "case variant"}]
    capitalized = http.get("/api/dictionary/search?q=Crane").json()["items"]
    assert capitalized[:2] == [{"word": "Crane", "match": "exact"}, {"word": "crane", "match": "case variant"}]
    settings = http.get("/api/settings").json()
    settings["exclude_multiword_expressions"] = True
    assert http.put("/api/settings", json=settings).status_code == 200
    assert "lucid dream" not in [item["word"] for item in http.get("/api/dictionary/search?q=lucid").json()["items"]]
    assert http.get("/api/dictionary/search?q=well-").json()["items"][0]["word"] == "well-being"


def test_real_dictionary_lookup_across_request_threads():
    if not (settings.wn_dir / "wn.db").exists():
        pytest.skip("OEWN has not been bootstrapped")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(dictionary_service.lookup, ["lucid", "good", "lucid", "good"]))
    assert all(result and result["senses"] for result in results)
    assert any(sense["antonyms"] for sense in results[1]["senses"])
    lower_crane = dictionary_service.lookup("crane")
    upper_crane = dictionary_service.lookup("Crane")
    assert lower_crane and any("bird" in sense["definition"] for sense in lower_crane["senses"])
    assert upper_crane and any("writer" in sense["definition"] for sense in upper_crane["senses"])


def test_relations_never_list_the_word_itself():
    if not (settings.wn_dir / "wn.db").exists():
        pytest.skip("OEWN has not been bootstrapped")
    for word in ("retro", "increase"):
        entry = dictionary_service.lookup(word)
        assert entry and entry["senses"]
        for sense in entry["senses"]:
            assert word not in sense["synonyms"]
            assert word not in sense["antonyms"]
            assert word not in sense["derivatives"]
    assert any("music" in sense["derivatives"] for sense in dictionary_service.lookup("musical")["senses"])


def test_audio_metadata_missing_timeout_and_cached_fallback(client, monkeypatch):
    http, engine = client
    register(http, "AudioUser")

    class FakeClient:
        def __init__(self, mode):
            self.mode = mode

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, **_kwargs):
            request = httpx.Request("GET", url)
            if self.mode == "timeout":
                raise httpx.ConnectTimeout("Connection failed", request=request)
            if "wiktionary" in url:
                images = [] if self.mode == "missing" else [{"title": "File:En-us-good.ogg"}]
                return httpx.Response(200, json={"query": {"pages": {"1": {"images": images}}}}, request=request)
            return httpx.Response(200, json={"query": {"pages": {"2": {"imageinfo": [{
                "url": "https://upload.wikimedia.org/good.ogg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:En-us-good.ogg",
                "extmetadata": {"Artist": {"value": "<b>Speaker</b>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}, "Credit": {"value": "Recorded by Speaker"}},
            }]}}}}, request=request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient("success"))
    success = http.get("/api/dictionary/good/audio")
    assert success.status_code == 200
    assert success.json()["creator"] == "Speaker"
    assert success.json()["license"] == "CC BY-SA 4.0"
    assert success.json()["source_url"].endswith("En-us-good.ogg")

    with Session(engine) as db:
        cache = db.get(AudioCache, "good")
        cache.fetched_at = datetime.now(timezone.utc) - timedelta(days=8)
        db.commit()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient("timeout"))
    assert http.get("/api/dictionary/good/audio").json()["creator"] == "Speaker"
    unavailable = http.get("/api/dictionary/lucid/audio")
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "audio_unavailable"
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient("missing"))
    missing = http.get("/api/dictionary/lucid/audio")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "audio_not_found"


def test_example_mentions_term():
    assert example_mentions_term("choking exasperation and wordless shame", "wordless")
    assert not example_mentions_term("a mute appeal", "wordless")
    assert example_mentions_term("The dog barked all night", "dog")
    assert not example_mentions_term("dogmatic assumptions", "dog")
    assert example_mentions_term("a hot diggity dog", "diggity dog")
