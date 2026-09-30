"""Background workers so the window never freezes while Hudu is busy."""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from voiceagent import audio, llm, stt, tts
from voiceagent.config import CONFIG


class _Signals(QObject):
    level = Signal(float)
    finished = Signal(bytes)


class RecorderTask(QRunnable):
    """Captures the mic until the button is released, then transcribes it."""

    def __init__(self, stop_event: threading.Event) -> None:
        super().__init__()
        self.stop_event = stop_event
        self.signals = _Signals()
        self.error: str | None = None

    def run(self) -> None:  # noqa: D102
        try:
            pcm = audio.record_until_silence(
                on_level=lambda level: self.signals.level.emit(min(1.0, level * 12)),
                stop_event=self.stop_event,
            )
        except Exception as exc:  # noqa: BLE001
            self.error = f"microphone error: {exc}"
            traceback.print_exc()
            self.signals.finished.emit(b"")
            return

        if len(pcm) < CONFIG.sample_rate // 4:
            self.signals.finished.emit(b"")
            return

        try:
            transcript = stt.transcribe(audio.pcm_to_wav_bytes(pcm))
            self.signals.finished.emit(transcript.encode("utf-8", "replace"))
        except stt.TranscriptionError as exc:
            self.error = str(exc)
            self.signals.finished.emit(b"")
        except Exception as exc:  # noqa: BLE001
            self.error = f"transcription failed: {exc}"
            traceback.print_exc()
            self.signals.finished.emit(b"")


class _TurnSignals(QObject):
    chunk = Signal(str)
    trace = Signal(list)
    finished = Signal(str)
    failed = Signal(str)


class TurnTask(QRunnable):
    """Runs one agent turn, speaks the reply, and reports both back."""

    def __init__(self, agent: llm.Agent, request: str, speak: bool = True) -> None:
        super().__init__()
        self.agent = agent
        self.request = request
        self.speak = speak
        self.signals = _TurnSignals()

    def run(self) -> None:  # noqa: D102
        try:
            chunks: list[str] = []
            for chunk in self.agent.respond(self.request):
                chunks.append(chunk)
                if self.speak and CONFIG.tts_enabled:
                    tts.speak(chunk)

            self.signals.trace.emit(list(self.agent.last_tool_trace))
            reply = " ".join(c.strip() for c in chunks if c.strip()) or "Done."
            self.signals.finished.emit(reply)
        except llm.AgentError as exc:
            self.signals.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            tts.stop()


class ConfirmTask(QRunnable):
    """Sends or clears a typed WhatsApp draft, then speaks the outcome."""

    def __init__(self, send: bool) -> None:
        super().__init__()
        self.send = send
        self.signals = _TurnSignals()
        self.result: dict | None = None

    def run(self) -> None:  # noqa: D102
        from voiceagent.tools import whatsapp

        try:
            self.result = whatsapp.confirm(send=self.send)
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        message = (self.result or {}).get("message", "Done.")
        self.signals.trace.emit([f"whatsapp_confirm(send={str(self.send).lower()}) -> ok={(self.result or {}).get('ok')}"])
        if CONFIG.tts_enabled:
            tts.speak(message)
            tts.stop()
        self.signals.finished.emit(message)


def pool() -> QThreadPool:
    return QThreadPool.globalInstance()
