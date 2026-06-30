"""Realtime voice I/O layer (Mic → STT → LLM → TTS → speaker).

A **separate realtime layer**, not a Partners channel: it drives
``ChatOrchestrator`` directly and consumes ``StreamBus`` ``CONTENT`` tokens so
the assistant's final answer can be spoken sentence-by-sentence *while the LLM
is still generating* — and a barge-in can cancel the in-flight turn instantly.
This is why it bypasses the text/turn-based partner ``MessageBus``.

STT/TTS reuse the catalog-driven facade in :mod:`deeptutor.services.voice`
(``transcribe_audio`` / ``synthesize_speech``), so providers are configured
through the same Settings > Voice catalog as the REST ``/voice`` endpoints.

Layout:

* :mod:`~deeptutor.services.voice_realtime.chunker` — sentence chunker
* :mod:`~deeptutor.services.voice_realtime.vad`      — shared endpointing constants
* :mod:`~deeptutor.services.voice_realtime.pipeline` — one turn: STT → LLM → TTS
* :mod:`~deeptutor.services.voice_realtime.session`  — per-connection state + barge-in
"""

from __future__ import annotations

from deeptutor.services.voice_realtime.chunker import SentenceChunker

__all__ = ["SentenceChunker"]
