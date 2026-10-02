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
from app.models import AudioCache, Card, ExampleSentenceCache, LLMSettings, ReviewLog, StudySession, User, WordProgress


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


def test_llm_settings_persistence_key_lifecycle_and_isolation(client):
    http, engine = client
    endpoint = "/api/settings/llm"
    config = {"base_url": "http://localhost:11434/v1/", "model": " local-model ", "api_key": "test-secret"}
    assert http.get(endpoint).status_code == 401
    assert http.put(endpoint, json=config).status_code == 401
    register(http, "LLMReader")
    assert http.get(endpoint).json() == {"base_url": "https://api.openai.com/v1", "model": "", "has_api_key": False}
    saved = http.put(endpoint, json=config)
    assert saved.status_code == 200, saved.text
    expected = {"base_url": "http://localhost:11434/v1", "model": "local-model", "has_api_key": True}
    assert saved.json() == expected
    assert http.get(endpoint).json() == expected
    for key in (None, "replacement-secret", "", "new-secret"):
        response = http.put(endpoint, json={**config, "api_key": key})
        assert response.status_code == 200, response.text
        assert "api_key" not in response.json()
        assert response.json()["has_api_key"] is (key != "")
        with Session(engine) as db:
            stored = db.scalar(select(LLMSettings))
            assert stored.api_key == ("test-secret" if key is None else key or None)
    assert http.put(endpoint, json={"base_url": config["base_url"], "model": "another-model"}).json()["has_api_key"]
    http.post("/api/auth/logout")
    register(http, "OtherLLMReader")
    assert http.get(endpoint).json()["has_api_key"] is False
    http.put(endpoint, json={"base_url": "http://localhost:8080/v1", "model": "second-model"})
    http.post("/api/auth/logout")
    assert http.post("/api/auth/login", json={"username": "LLMReader", "password": "long-enough-password"}).status_code == 200
    assert http.get(endpoint).json() == {**expected, "model": "another-model"}
    with Session(engine) as db:
        user = db.scalar(select(User).where(User.username == "LLMReader"))
        db.delete(user)
        db.commit()
        assert db.get(LLMSettings, user.id) is None
        assert db.scalar(select(LLMSettings)).model == "second-model"


@pytest.mark.parametrize("base_url,model", [
    ("file:///tmp/model", "model"),
    ("https://user:password@example.com/v1", "model"),
    ("https://example.com/v1?api_key=secret", "model"),
    ("https://example.com/v1#fragment", "model"),
    ("https://example.com/v1", "   "),
])
def test_llm_settings_validation(client, base_url, model):
    http, engine = client
    register(http, "LLMReader")
    assert http.put("/api/settings/llm", json={"base_url": base_url, "model": model}).status_code == 422
    with Session(engine) as db:
        assert db.scalar(select(LLMSettings)) is None


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


def test_word_list_membership_tracks_add_and_remove(client):
    http, _ = client
    register(http, "Collector")
    first = http.post("/api/lists", json={"name": "First", "direction": "bidirectional"}).json()["id"]
    second = http.post("/api/lists", json={"name": "Second", "direction": "bidirectional"}).json()["id"]
    assert [(item["id"], item["contains"], item["entry_id"]) for item in http.get("/api/words/lucid/lists").json()] == [(first, False, None), (second, False, None)]
    entry_id = http.post(f"/api/lists/{second}/entries", json={"word": "Lucid"}).json()["id"]
    assert [(item["id"], item["contains"], item["entry_id"]) for item in http.get("/api/words/LUCID/lists").json()] == [(first, False, None), (second, True, entry_id)]
    assert http.delete(f"/api/lists/{second}/entries/{entry_id}").status_code == 204
    assert [item["contains"] for item in http.get("/api/words/lucid/lists").json()] == [False, False]


def test_learned_words_include_every_card_word_and_no_uncarded_words(client):
    http, engine = client
    register(http, "CardCollection")
    http.put("/api/settings", json={"learn_batch_size": 1, "review_batch_size": 1, "pool_multiplier": 1})
    list_id = http.post("/api/lists", json={"name": "Study"}).json()["id"]
    for word in ("Lucid", "Resilient"):
        assert http.post(f"/api/lists/{list_id}/entries", json={"word": word}).status_code == 201
    assert http.get("/api/words/learned").json() == []

    http.post("/api/study/sessions", json={"kind": "learning", "direction": "w2m"})
    learned = http.get("/api/words/learned").json()
    assert [(item["normalized_word"], len(item["cards"])) for item in learned] == [("lucid", 1)]
    assert http.get("/api/words/learned?q=resilient").json() == []
    assert len(http.get("/api/words/learned?q=LUCI").json()) == 1

    http.put("/api/words/Lucid/status", json={"status": "familiar"})
    assert http.get("/api/words/learned").json()[0]["status"] == "familiar"
    http.delete(f"/api/lists/{list_id}")
    assert http.get("/api/words/learned").json()[0]["normalized_word"] == "lucid"

    with Session(engine) as db:
        progress = db.scalar(select(WordProgress).where(WordProgress.normalized_word == "lucid"))
        assert progress is not None
        db.delete(progress)
        db.commit()
    assert http.get("/api/words/learned").json()[0]["normalized_word"] == "lucid"


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
    resumed = http.get(f"/api/study/sessions/{session_id}/next").json()
    assert resumed["presentation_token"] == token
    assert resumed["item"]["prompt"] == prompt["item"]["prompt"]
    assert http.post(f"/api/study/sessions/{session_id}/answer", json={"presentation_token": token, "rating": 4}).status_code == 409
    assert [item["id"] for item in http.get("/api/study/overview").json()["active_sessions"]] == [session_id]
    revealed = http.post(f"/api/study/sessions/{session_id}/reveal", json={"presentation_token": token}).json()
    assert revealed["item"]["answer"]["senses"][0]["definition"] == "Definition of lucid"
    resumed = http.get(f"/api/study/sessions/{session_id}/next").json()
    assert resumed["presentation_token"] == token
    assert resumed["revealed"] is True
    assert resumed["item"]["answer"] == revealed["item"]["answer"]
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
    assert [item["id"] for item in http.get("/api/study/overview").json()["active_sessions"]] == [reverse["id"]]
    skipped = http.post(f"/api/study/sessions/{reverse['id']}/skip", json={"presentation_token": reverse_prompt["presentation_token"], "status": "familiar"})
    assert skipped.json()["status"] == "completed"
    assert http.get("/api/study/overview").json()["new"] == {"w2m": 0, "m2w": 0}


def test_session_progress_uses_available_cards_when_batch_is_larger(client):
    http, engine = client
    register(http, "SmallBatch")
    http.put("/api/settings", json={"learn_batch_size": 10, "review_batch_size": 20})
    list_id = http.post("/api/lists", json={"name": "Short", "direction": "w2m"}).json()["id"]
    http.post(f"/api/lists/{list_id}/entries", json={"word": "Lucid"})

    learning = http.post("/api/study/sessions", json={"kind": "learning", "direction": "w2m"}).json()
    assert (learning["target_count"], learning["pool_size"]) == (1, 1)
    prompt = http.get(f"/api/study/sessions/{learning['id']}/next").json()
    assert prompt["session"]["target_count"] == 1
    assert http.get("/api/study/overview").json()["active_sessions"][0]["target_count"] == 1
    http.post(f"/api/study/sessions/{learning['id']}/reveal", json={"presentation_token": prompt["presentation_token"]})
    http.post(f"/api/study/sessions/{learning['id']}/answer", json={"presentation_token": prompt["presentation_token"], "rating": 4})

    with Session(engine) as db:
        card = db.scalar(select(Card))
        assert card is not None
        card.due = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    review = http.post("/api/study/sessions", json={"kind": "review", "direction": "w2m"}).json()
    assert (review["target_count"], review["pool_size"]) == (1, 1)
    assert http.get(f"/api/study/sessions/{review['id']}/next").json()["session"]["target_count"] == 1


def test_start_resumes_only_the_matching_session_kind_and_direction(client):
    http, engine = client
    register(http, "FourSessions")
    user_id = http.get("/api/auth/me").json()["id"]
    combinations = [(kind, direction) for kind in ("learning", "review") for direction in ("w2m", "m2w")]
    with Session(engine) as db:
        sessions = [StudySession(user_id=user_id, kind=kind, direction=direction, target_count=2, pool_size=2) for kind, direction in combinations]
        db.add_all(sessions)
        db.commit()
        session_ids = {(session.kind, session.direction): session.id for session in sessions}

    overview = http.get("/api/study/overview").json()
    assert {(item["kind"], item["direction"]): item["id"] for item in overview["active_sessions"]} == session_ids
    for kind, direction in combinations:
        response = http.post("/api/study/sessions", json={"kind": kind, "direction": direction})
        assert response.status_code == 201, response.text
        assert response.json()["id"] == session_ids[(kind, direction)]


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


def test_llm_sentence_generation_uses_owned_config_and_selected_sense(client, monkeypatch):
    http, _ = client
    endpoint = "/api/dictionary/lucid/examples"
    assert http.post(endpoint, json={"sense_index": 0}).status_code == 401
    register(http, "ExampleReader")
    assert http.post(endpoint, json={"sense_index": 0}).status_code == 409
    config = {"base_url": "http://localhost:11434/v1", "model": "my-model", "api_key": "private-key"}
    assert http.put("/api/settings/llm", json=config).status_code == 200
    sense = {"part_of_speech": "adjective", "definition": "Able to think clearly", "examples": [], "synonyms": [], "antonyms": [], "derivatives": []}
    original_lookup = dictionary_service.lookup
    monkeypatch.setattr(dictionary_service, "lookup", lambda word: {**original_lookup(word), "senses": [original_lookup(word)["senses"][0], sense]} if original_lookup(word) else None)
    examples = ["She gave a lucid account of the meeting.", "After resting, he felt lucid again.", "The patient was lucid during the examination."]
    requests = []
    mode = "success"

    def respond(request):
        requests.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("private-key should not be exposed", request=request)
        if mode == "offline":
            raise httpx.ConnectError("private-key should not be exposed", request=request)
        if mode == "unauthorized":
            return httpx.Response(401, json={"error": "private-key"})
        if mode == "rate_limit":
            return httpx.Response(429, json={"error": "private-key"})
        if mode == "invalid":
            content = "not JSON"
        elif mode == "wrong_word":
            content = json.dumps({"examples": ["A clear account.", "An easy account.", "A bright account."]})
        elif mode == "duplicate":
            content = json.dumps({"examples": [examples[0]] * 3})
        else:
            content = "```json\n" + json.dumps({"examples": examples}) + "\n```"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(respond), **kwargs))
    assert http.post(endpoint, json={"sense_index": 2}).status_code == 404
    assert http.post(endpoint, json={"sense_index": -1}).status_code == 422
    assert http.post("/api/dictionary/missing/examples", json={"sense_index": 0}).status_code == 404
    assert not requests
    success = http.post(endpoint, json={"sense_index": 1})
    assert success.status_code == 200, success.text
    assert success.json() == {"examples": examples}
    assert requests[0].url == "http://localhost:11434/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer private-key"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "my-model"
    assert json.loads(payload["messages"][1]["content"]) == {"word": "lucid", "part_of_speech": "adjective", "definition": sense["definition"]}
    for mode, status in [("timeout", 504), ("offline", 502), ("unauthorized", 502), ("rate_limit", 503), ("invalid", 502), ("wrong_word", 502), ("duplicate", 502)]:
        failure = http.post(endpoint, json={"sense_index": 1})
        assert failure.status_code == status, failure.text
        assert "private-key" not in failure.text
        assert http.get("/api/dictionary/lucid").json()["senses"][1]["generated_examples"] == examples
    mode = "success"
    assert http.put("/api/settings/llm", json={**config, "api_key": ""}).status_code == 200
    assert http.post(endpoint, json={"sense_index": 1}).status_code == 200
    assert "authorization" not in requests[-1].headers
    http.post("/api/auth/logout")
    register(http, "OtherExampleReader")
    count = len(requests)
    assert http.post(endpoint, json={"sense_index": 0}).status_code == 409
    assert len(requests) == count


def test_generated_example_cache_persistence_identity_clear_and_isolation(client, monkeypatch):
    http, engine = client
    register(http, "CachedReader")
    owner_id = http.get("/api/auth/me").json()["id"]
    http.put("/api/settings/llm", json={"base_url": "http://localhost:11434/v1", "model": "local"})
    original = dictionary_service.lookup("lucid")
    senses = [original["senses"][0], {**original["senses"][0], "definition": "Able to think clearly"}]
    monkeypatch.setattr(dictionary_service, "lookup", lambda word: {**original, "word": word, "senses": senses})
    calls = []

    async def generate(_config, word, sense):
        calls.append(sense["definition"])
        return [f"A {word} example {index} from batch {len(calls)} for {sense['definition']}." for index in range(3)]

    monkeypatch.setattr("app.main.generate_examples", generate)
    endpoint = "/api/dictionary/lucid/examples"
    first = http.post(endpoint, json={"sense_index": 0}).json()["examples"]
    second = http.post(endpoint, json={"sense_index": 1}).json()["examples"]
    # Fresh requests load stored examples without calling the provider.
    assert [sense["generated_examples"] for sense in http.get("/api/dictionary/lucid").json()["senses"]] == [first, second]
    assert len(calls) == 2
    replacement = http.post(endpoint, json={"sense_index": 0}).json()["examples"]
    assert replacement != first
    first = replacement
    assert http.get("/api/dictionary/lucid").json()["senses"][0]["generated_examples"] == replacement
    assert all(not sense["generated_examples"] for sense in http.get("/api/dictionary/Lucid").json()["senses"])
    senses.reverse()
    assert [sense["generated_examples"] for sense in http.get("/api/dictionary/lucid").json()["senses"]] == [second, first]
    senses[1] = {**senses[1], "definition": "A changed definition"}
    assert http.get("/api/dictionary/lucid").json()["senses"][1]["generated_examples"] == []
    http.post("/api/auth/logout")
    assert http.delete(endpoint + "/0").status_code == 401
    register(http, "OtherCachedReader")
    assert all(not sense["generated_examples"] for sense in http.get("/api/dictionary/lucid").json()["senses"])
    assert http.delete(endpoint + "/0").status_code == 204
    http.post("/api/auth/logout")
    http.post("/api/auth/login", json={"username": "CachedReader", "password": "long-enough-password"})
    assert http.get("/api/dictionary/lucid").json()["senses"][0]["generated_examples"] == second
    assert http.delete(endpoint + "/-1").status_code == 404
    assert http.delete(endpoint + "/2").status_code == 404
    assert http.delete(endpoint + "/0").status_code == 204
    assert http.delete(endpoint + "/0").status_code == 204
    assert http.get("/api/dictionary/lucid").json()["senses"][0]["generated_examples"] == []
    with Session(engine) as db:
        assert len(db.scalars(select(ExampleSentenceCache)).all()) == 1
        db.delete(db.get(User, owner_id))
        db.commit()
        assert db.scalars(select(ExampleSentenceCache)).all() == []


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
