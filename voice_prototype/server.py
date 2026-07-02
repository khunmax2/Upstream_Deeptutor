"""FastAPI WebSocket server for the voice-call prototype.

Mirrors the planned realtime I/O layer in miniature: one WebSocket = one call.
The browser does mic capture + VAD endpointing and sends one utterance (a webm
blob) per turn; the server runs STT → LLM(stream) → per-sentence TTS and streams
audio chunks back, tagging each turn with per-stage latency.

Protocol (server → client), all JSON except the audio payload frames:
  {"type":"transcript","text":...}            user speech, recognised
  {"type":"stage","stage":"stt","ms":...}     per-stage latency
  {"type":"assistant_text","text":...}        full assistant reply (running)
  {"type":"audio","seq":n,"text":...}  then a following BINARY frame = mp3
  {"type":"done","total_ms":...,"first_audio_ms":...}
  {"type":"error","message":...}
"""

from __future__ import annotations

from pathlib import Path
import time

from config import CONFIG
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pipeline import SentenceChunker, clean_for_speech, stream_llm, synthesize, transcribe
from providers import normalize_thai_for_tts

app = FastAPI(title="DeepTutor Voice Prototype")
STATIC = Path(__file__).parent / "static"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "tts_backend": CONFIG.tts_backend, "llm_model": CONFIG.llm_model}


@app.websocket("/ws")
async def voice_ws(ws: WebSocket) -> None:
    await ws.accept()
    history: list[dict] = [{"role": "system", "content": CONFIG.system_prompt}]
    try:
        while True:
            message = await ws.receive()
            audio = message.get("bytes")
            if audio is None:  # control text frame (ignored in this prototype)
                continue
            await _handle_turn(ws, audio, history)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # keep the socket alive across one bad turn
        await _safe_send(ws, {"type": "error", "message": str(exc)})


async def _handle_turn(ws: WebSocket, audio: bytes, history: list[dict]) -> None:
    turn_t0 = time.perf_counter()

    # ── STT ──
    try:
        text, stt_s = await transcribe(audio)
    except Exception as exc:
        await _safe_send(ws, {"type": "error", "message": f"STT: {exc}"})
        return
    if not text:
        await _safe_send(ws, {"type": "error", "message": "ไม่ได้ยินเสียงพูด"})
        return
    await _safe_send(ws, {"type": "transcript", "text": text})
    await _safe_send(ws, {"type": "stage", "stage": "stt", "ms": round(stt_s * 1000)})

    history.append({"role": "user", "content": text})

    # ── LLM stream → sentence chunker → TTS ──
    chunker = SentenceChunker(max_chars=CONFIG.chunk_max_chars)
    reply_parts: list[str] = []
    seq = 0
    first_token_at: float | None = None
    first_audio_at: float | None = None
    llm_start = time.perf_counter()

    async def speak(chunk: str) -> None:
        nonlocal seq, first_audio_at
        audio_bytes, _ctype, _tts_s = await synthesize(chunk)
        if not audio_bytes:
            return
        if first_audio_at is None:
            first_audio_at = time.perf_counter()
            await _safe_send(
                ws, {"type": "stage", "stage": "tts_first", "ms": round(_tts_s * 1000)}
            )
        await _safe_send(ws, {"type": "audio", "seq": seq, "text": chunk})
        await ws.send_bytes(audio_bytes)
        seq += 1

    try:
        async for token in stream_llm(history):
            if first_token_at is None:
                first_token_at = time.perf_counter()
                await _safe_send(
                    ws,
                    {
                        "type": "stage",
                        "stage": "llm_ttft",
                        "ms": round((first_token_at - llm_start) * 1000),
                    },
                )
            reply_parts.append(token)
            for chunk in chunker.feed(token):
                await speak(chunk)
        tail = chunker.flush()
        if tail:
            await speak(tail)
    except Exception as exc:
        await _safe_send(ws, {"type": "error", "message": f"LLM/TTS: {exc}"})
        return

    reply = "".join(reply_parts).strip()
    history.append({"role": "assistant", "content": reply})
    await _safe_send(ws, {"type": "assistant_text", "text": reply})
    await _safe_send(
        ws,
        {
            "type": "done",
            "total_ms": round((time.perf_counter() - turn_t0) * 1000),
            "first_audio_ms": (
                round((first_audio_at - turn_t0) * 1000) if first_audio_at else None
            ),
        },
    )


async def _safe_send(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_json(payload)
    except Exception:
        pass


# ── MVP: text-in chat turn (browser does STT/TTS via Web Speech API) ────────
@app.get("/mvp")
async def mvp() -> FileResponse:
    return FileResponse(STATIC / "mvp.html")


@app.websocket("/ws/chat")
async def chat_ws(ws: WebSocket) -> None:
    """MVP socket: receive recognised text, stream the reply as spoken sentences.

    The browser handles microphone STT and speaker TTS (Web Speech API), so this
    server only needs the LLM brain — no audio, no STT/TTS keys. When the
    TokenMind endpoint arrives, the server-side ``providers.py`` path takes over
    behind the same idea.
    """
    await ws.accept()
    history: list[dict] = [{"role": "system", "content": CONFIG.system_prompt}]
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") != "user_text":
                continue
            text = (msg.get("text") or "").strip()
            if text:
                await _handle_text_turn(ws, text, history)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await _safe_send(ws, {"type": "error", "message": str(exc)})


async def _handle_text_turn(ws: WebSocket, text: str, history: list[dict]) -> None:
    history.append({"role": "user", "content": text})
    chunker = SentenceChunker(max_chars=CONFIG.chunk_max_chars)
    reply_parts: list[str] = []
    seq = 0
    t0 = time.perf_counter()
    first_token_at: float | None = None

    async def emit(chunk: str) -> None:
        nonlocal seq
        spoken = normalize_thai_for_tts(clean_for_speech(chunk))
        if spoken:
            await _safe_send(ws, {"type": "assistant_sentence", "seq": seq, "text": spoken})
            seq += 1

    try:
        async for token in stream_llm(history):
            if first_token_at is None:
                first_token_at = time.perf_counter()
                await _safe_send(
                    ws,
                    {
                        "type": "stage",
                        "stage": "llm_ttft",
                        "ms": round((first_token_at - t0) * 1000),
                    },
                )
            reply_parts.append(token)
            for chunk in chunker.feed(token):
                await emit(chunk)
        tail = chunker.flush()
        if tail:
            await emit(tail)
    except Exception as exc:
        await _safe_send(ws, {"type": "error", "message": f"LLM: {exc}"})
        return

    reply = "".join(reply_parts).strip()
    history.append({"role": "assistant", "content": reply})
    await _safe_send(
        ws,
        {
            "type": "assistant_done",
            "reply": reply,
            "total_ms": round((time.perf_counter() - t0) * 1000),
        },
    )


# Serve the rest of /static (if any assets are added later).
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port)
