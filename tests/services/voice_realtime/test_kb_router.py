"""Layer-2 KB router: meta / content / unrelated from the KB manifest.
Off by default; a failure or no-content ⇒ None (caller keeps RAG-on). LLM mocked."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.voice_realtime import kb_router as kr

_MANIFEST = {
    "kb_name": "LAWs_thai",
    "summary": "กฎหมายไทยเรื่องข้อมูลส่วนบุคคลและข้อมูลข่าวสาร",
    "documents": [
        {
            "file": "pdpa.pdf",
            "title": "พ.ร.บ. คุ้มครองข้อมูลส่วนบุคคล",
            "topics": ["PDPA", "สิทธิเจ้าของข้อมูล"],
        },
        {
            "file": "law_info2540.pdf",
            "title": "พ.ร.บ. ข้อมูลข่าวสารของราชการ",
            "topics": ["ข้อมูลข่าวสาร"],
        },
    ],
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (kr.FLAG_ENV, kr.MODEL_ENV, kr.BASE_URL_ENV, kr.API_KEY_ENV, kr.BINDING_ENV):
        monkeypatch.delenv(name, raising=False)


def _mock_complete(monkeypatch, reply: str | Exception):
    calls: dict[str, Any] = {}

    async def fake(prompt: str, **kwargs: Any) -> str:
        calls["prompt"] = prompt
        calls["kwargs"] = kwargs
        if isinstance(reply, Exception):
            raise reply
        return reply

    import deeptutor.services.llm as llm_module

    monkeypatch.setattr(llm_module, "complete", fake)
    return calls


# ── flag + pure helpers ──


def test_disabled_by_default():
    assert not kr.kb_routing_enabled()


def test_enabled_by_flag(monkeypatch):
    monkeypatch.setenv(kr.FLAG_ENV, "1")
    assert kr.kb_routing_enabled()


def test_has_content():
    assert kr.has_content([_MANIFEST])
    assert not kr.has_content([{"kb_name": "x", "documents": [], "summary": ""}])
    assert not kr.has_content([])


def test_catalogue_names_titles_and_topics():
    cat = kr._catalogue([_MANIFEST])
    assert "LAWs_thai" in cat
    assert "พ.ร.บ. คุ้มครองข้อมูลส่วนบุคคล" in cat
    assert "PDPA" in cat


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"route": "meta"}', "meta"),
        ('{"route": "unrelated"}', "unrelated"),
        ('{"route": "content"}', "content"),
        ("garbage no json", "content"),  # unparseable biases to content (RAG)
        ('{"route": "weird"}', "content"),
    ],
)
def test_parse_route(raw, expected):
    assert kr._parse_route(raw) == expected


# ── route() ──


@pytest.mark.asyncio
async def test_route_off_returns_none(monkeypatch):
    _mock_complete(monkeypatch, '{"route": "meta"}')
    assert await kr.route("อะไรก็ตาม", [_MANIFEST]) is None  # flag off


@pytest.mark.asyncio
async def test_route_no_content_returns_none(monkeypatch):
    monkeypatch.setenv(kr.FLAG_ENV, "1")
    _mock_complete(monkeypatch, '{"route": "meta"}')
    assert await kr.route("อะไร", [{"kb_name": "x", "documents": []}]) is None


@pytest.mark.asyncio
async def test_route_meta_and_unrelated(monkeypatch):
    monkeypatch.setenv(kr.FLAG_ENV, "1")
    _mock_complete(monkeypatch, '{"route": "meta"}')
    assert await kr.route("มีเอกสารอะไรบ้าง", [_MANIFEST]) == "meta"
    _mock_complete(monkeypatch, '{"route": "unrelated"}')
    assert await kr.route("ราคาทองเท่าไหร่", [_MANIFEST]) == "unrelated"


@pytest.mark.asyncio
async def test_route_failure_returns_none(monkeypatch):
    monkeypatch.setenv(kr.FLAG_ENV, "1")
    _mock_complete(monkeypatch, RuntimeError("429"))
    assert await kr.route("อะไร", [_MANIFEST]) is None


# ── compose_meta_answer() ──


@pytest.mark.asyncio
async def test_compose_meta_answer(monkeypatch):
    calls = _mock_complete(monkeypatch, "มีสองฉบับ: PDPA และ พ.ร.บ.ข้อมูลข่าวสาร ครับ")
    answer = await kr.compose_meta_answer("มีเอกสารอะไรบ้าง", [_MANIFEST])
    assert answer and "PDPA" in answer
    assert "response_format" not in calls["kwargs"]  # plain spoken text, not JSON


@pytest.mark.asyncio
async def test_compose_meta_answer_failure_returns_none(monkeypatch):
    _mock_complete(monkeypatch, RuntimeError("boom"))
    assert await kr.compose_meta_answer("q", [_MANIFEST]) is None


# ── load_manifests() ──


@pytest.mark.asyncio
async def test_load_manifests_tags_kb_name(monkeypatch):
    async def fake_get(kb_name, kb_base_dir=None, **kw):
        return {"summary": "s", "documents": [{"file": "a.pdf", "title": "A", "topics": []}]}

    import deeptutor.services.rag.content_manifest as cm

    monkeypatch.setattr(cm, "get_or_build_manifest", fake_get)
    out = await kr.load_manifests(["KB1", "KB2"])
    assert [m["kb_name"] for m in out] == ["KB1", "KB2"]


@pytest.mark.asyncio
async def test_load_manifests_skips_failures(monkeypatch):
    async def fake_get(kb_name, kb_base_dir=None, **kw):
        if kb_name == "bad":
            raise RuntimeError("no index")
        return {"summary": "s", "documents": [{"file": "a", "title": "A"}]}

    import deeptutor.services.rag.content_manifest as cm

    monkeypatch.setattr(cm, "get_or_build_manifest", fake_get)
    out = await kr.load_manifests(["good", "bad"])
    assert [m["kb_name"] for m in out] == ["good"]
