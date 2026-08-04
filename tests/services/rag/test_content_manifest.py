"""Per-KB content manifest: built lazily from docstore text, cached in
metadata.json, invalidated when the document set changes. LLM is mocked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.rag import content_manifest as cm


def _make_kb(
    tmp_path: Path,
    *,
    kb_name: str = "KB",
    file_hashes: dict[str, str] | None = None,
    chunks: dict[str, list[str]] | None = None,
    ready: bool = True,
) -> str:
    """Create a minimal on-disk KB; return its ``kb_base_dir``."""
    kb_dir = tmp_path / kb_name
    kb_dir.mkdir(parents=True)
    (kb_dir / "metadata.json").write_text(
        json.dumps({"name": kb_name, "file_hashes": file_hashes or {"a.pdf": "h1"}}),
        encoding="utf-8",
    )
    if ready:
        version = kb_dir / "version-1"
        version.mkdir()
        chunks = chunks or {"a.pdf": ["chunk one text", "chunk two text"]}
        data: dict[str, Any] = {}
        i = 0
        for fname, texts in chunks.items():
            for text in texts:
                data[f"n{i}"] = {"__data__": {"text": text, "metadata": {"file_name": fname}}}
                i += 1
        (version / "docstore.json").write_text(
            json.dumps({"docstore/data": data}), encoding="utf-8"
        )
    return str(tmp_path)


def _mock_complete(monkeypatch, replies: list[str]):
    calls: dict[str, Any] = {"count": 0, "prompts": []}
    queue = list(replies)

    async def fake(prompt: str, **kwargs: Any) -> str:
        calls["count"] += 1
        calls["prompts"].append(prompt)
        return queue.pop(0) if queue else '{"summary": "the kb"}'

    import deeptutor.services.llm as llm_module

    monkeypatch.setattr(llm_module, "complete", fake)
    return calls


# ── pure helpers ──


def test_docstore_texts_groups_by_file(tmp_path):
    base = _make_kb(
        tmp_path,
        chunks={"a.pdf": ["a1", "a2"], "b.pdf": ["b1"]},
    )
    storage = Path(base) / "KB" / "version-1"
    grouped = cm._docstore_texts(storage)
    assert grouped == {"a.pdf": ["a1", "a2"], "b.pdf": ["b1"]}


def test_sample_text_respects_char_budget():
    chunks = ["x" * 100 for _ in range(50)]
    out = cm._sample_text(chunks, budget=250)
    assert len(out) <= 260  # budget + a couple of join separators, never the whole doc


def test_signature_changes_with_file_hashes():
    a = cm._signature({"file_hashes": {"a.pdf": "h1"}})
    b = cm._signature({"file_hashes": {"a.pdf": "h2"}})
    assert a != b
    assert a == cm._signature({"file_hashes": {"a.pdf": "h1"}})  # stable


# ── build + cache + invalidate ──


@pytest.mark.asyncio
async def test_build_and_cache_writes_manifest(tmp_path, monkeypatch):
    base = _make_kb(tmp_path, chunks={"a.pdf": ["law text about privacy"]})
    calls = _mock_complete(
        monkeypatch,
        [
            '{"title": "PDPA", "topics": ["privacy", "data"], "summary": "about privacy"}',
            '{"summary": "a privacy-law KB"}',
        ],
    )

    manifest = await cm.get_or_build_manifest("KB", base)

    assert manifest is not None
    assert manifest["summary"] == "a privacy-law KB"
    assert manifest["documents"][0]["title"] == "PDPA"
    assert manifest["documents"][0]["topics"] == ["privacy", "data"]
    assert calls["count"] == 2  # one doc + one kb-summary call
    # cached into metadata.json
    meta = json.loads((tmp_path / "KB" / "metadata.json").read_text(encoding="utf-8"))
    assert meta[cm.MANIFEST_KEY]["documents"][0]["title"] == "PDPA"


@pytest.mark.asyncio
async def test_second_call_uses_cache_no_llm(tmp_path, monkeypatch):
    base = _make_kb(tmp_path)
    _mock_complete(
        monkeypatch, ['{"title": "T", "topics": ["x"], "summary": "s"}', '{"summary": "kb"}']
    )
    await cm.get_or_build_manifest("KB", base)

    calls2 = _mock_complete(monkeypatch, [])  # fresh counter
    manifest = await cm.get_or_build_manifest("KB", base)
    assert manifest is not None
    assert calls2["count"] == 0  # served from cache, no LLM


@pytest.mark.asyncio
async def test_changed_documents_invalidate_cache(tmp_path, monkeypatch):
    base = _make_kb(tmp_path, file_hashes={"a.pdf": "h1"})
    _mock_complete(
        monkeypatch, ['{"title": "T1", "topics": [], "summary": "s"}', '{"summary": "kb1"}']
    )
    await cm.get_or_build_manifest("KB", base)

    # a document changed → new file_hashes → manifest must rebuild
    meta_path = tmp_path / "KB" / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["file_hashes"] = {"a.pdf": "h2"}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    calls = _mock_complete(
        monkeypatch, ['{"title": "T2", "topics": [], "summary": "s"}', '{"summary": "kb2"}']
    )
    manifest = await cm.get_or_build_manifest("KB", base)
    assert calls["count"] == 2  # rebuilt
    assert manifest["summary"] == "kb2"


@pytest.mark.asyncio
async def test_force_rebuilds_even_when_fresh(tmp_path, monkeypatch):
    base = _make_kb(tmp_path)
    _mock_complete(
        monkeypatch, ['{"title": "T", "topics": [], "summary": "s"}', '{"summary": "kb"}']
    )
    await cm.get_or_build_manifest("KB", base)
    calls = _mock_complete(
        monkeypatch, ['{"title": "T", "topics": [], "summary": "s"}', '{"summary": "kb2"}']
    )
    await cm.get_or_build_manifest("KB", base, force=True)
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_no_ready_index_returns_none(tmp_path, monkeypatch):
    base = _make_kb(tmp_path, ready=False)
    calls = _mock_complete(monkeypatch, [])
    assert await cm.get_or_build_manifest("KB", base) is None
    assert calls["count"] == 0  # never calls the LLM without text


@pytest.mark.asyncio
async def test_malformed_llm_output_falls_back(tmp_path, monkeypatch):
    base = _make_kb(tmp_path, chunks={"a.pdf": ["some text"]})
    _mock_complete(monkeypatch, ["not json at all", "also not json"])
    manifest = await cm.get_or_build_manifest("KB", base)
    assert manifest is not None
    doc = manifest["documents"][0]
    assert doc["file"] == "a.pdf"
    assert doc["title"] == "a.pdf"  # fell back to the file name
    assert doc["topics"] == []
