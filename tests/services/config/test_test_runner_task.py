"""The Task models page's "Run test" probes the task model.

Fork. v1.6.4 made the task model a catalog service shaped like ``llm`` and gave
its settings page the same Diagnostics panel, but the test runner never learned
the service: every run ended "[failed] Unsupported service: task" before a
request was sent. A configured task model is now probed through the same path
as the LLM, resolved from the ``task`` service; an empty one says it inherits
and probes the LLM it inherits from.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from deeptutor.services.config.test_runner import ConfigTestRunner, TestRun


def _profile(profile_id: str, model_id: str, model: str) -> dict[str, Any]:
    return {
        "id": profile_id,
        "name": "Gemini",
        "binding": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key": "test-key-not-real",
        "models": [{"id": model_id, "name": model, "model": model}],
    }


def _catalog(*, task_configured: bool) -> dict[str, Any]:
    llm = {
        "active_profile_id": "llm-p",
        "active_model_id": "llm-m",
        "profiles": [_profile("llm-p", "llm-m", "gemini-2.5-pro")],
    }
    task: dict[str, Any] = {"active_profile_id": None, "active_model_id": None, "profiles": []}
    if task_configured:
        task = {
            "active_profile_id": "task-p",
            "active_model_id": "task-m",
            "profiles": [_profile("task-p", "task-m", "gemini-2.5-flash")],
        }
    return {"version": 1, "services": {"llm": llm, "task": task}}


def _resolved(model: str) -> Any:
    return SimpleNamespace(
        model=model,
        api_key="test-key-not-real",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        effective_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        binding="gemini",
        provider_name="gemini",
        provider_mode="standard",
        api_version="",
        extra_headers={},
        wire_api="auto",
        reasoning_effort=None,
    )


def _run_task_test(catalog: dict[str, Any], resolved_model: str) -> tuple[TestRun, MagicMock]:
    runner = ConfigTestRunner()
    run = TestRun(id="task-1", service="task")
    resolve = MagicMock(return_value=_resolved(resolved_model))
    detection = SimpleNamespace(context_window=1_048_576, source="probe", detail="", detected_at=0)
    with (
        patch("deeptutor.services.config.test_runner.resolve_llm_runtime_config", resolve),
        patch("deeptutor.services.llm.complete", AsyncMock(return_value="OK")),
        patch(
            "deeptutor.services.config.test_runner.detect_context_window",
            AsyncMock(return_value=detection),
        ),
    ):
        runner._run_sync(run, catalog)
    return run, resolve


def _service_names(resolve: MagicMock) -> list[str]:
    return [call.kwargs.get("service_name", "llm") for call in resolve.call_args_list]


def test_a_configured_task_model_is_probed_from_the_task_service() -> None:
    run, resolve = _run_task_test(_catalog(task_configured=True), "gemini-2.5-flash")

    assert run.status == "completed", [e["message"] for e in run.events]
    assert _service_names(resolve) == ["task"]
    assert not any("Unsupported service" in e["message"] for e in run.events)


def test_an_empty_task_model_says_it_inherits_and_probes_the_llm() -> None:
    run, resolve = _run_task_test(_catalog(task_configured=False), "gemini-2.5-pro")

    assert run.status == "completed", [e["message"] for e in run.events]
    assert _service_names(resolve) == ["llm"]
    assert any("use the LLM" in e["message"] for e in run.events)
