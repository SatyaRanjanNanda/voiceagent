"""Text-to-speech via the Windows SAPI5 voices (offline, no extra keys)."""

from __future__ import annotations

import re
import threading
import time

from .config import CONFIG

_lock = threading.Lock()
_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        import pyttsx3

        _engine = pyttsx3.init()
        try:
            _engine.setProperty("rate", CONFIG.tts_rate)
        except Exception:  # noqa: BLE001 - some voices reject rate changes
            pass
    return _engine


def list_voices() -> list[str]:
    try:
        engine = _get_engine()
    except Exception:  # noqa: BLE001 - no SAPI voices installed
        return []
    names = []
    for voice in engine.getProperty("voices"):
        label = f"{voice.id} | {voice.name}"
        if voice.languages:
            label += f" [{','.join(voice.languages)}]"
        names.append(label)
    return names


def select_voice(index: int) -> str:
    try:
        engine = _get_engine()
        voices = engine.getProperty("voices")
        if not voices:
            return "no voices installed"
        index = max(0, min(index, len(voices) - 1))
        engine.setProperty("voice", voices[index].id)
        return voices[index].name
    except Exception as exc:  # noqa: BLE001
        return f"could not set voice: {exc}"


_URL = re.compile(r"https?://\S+")
_MARKDOWN = re.compile(r"[*_`#>\[\]]")


def _clean(text: str) -> str:
    text = _URL.sub("", text)
    text = _MARKDOWN.sub("", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def speak(text: str, interrupt: bool = True) -> None:
    """Speak text out loud. No-ops when TTS is disabled or text is empty."""
    if not CONFIG.tts_enabled:
        return
    spoken = _clean(text)
    if not spoken:
        return
    try:
        with _lock:
            engine = _get_engine()
            if interrupt:
                engine.stop()
            # Chunk long replies so Windows does not truncate them.
            for chunk in _chunks(spoken, 220):
                engine.say(chunk)
                engine.runAndWait()
    except Exception:  # noqa: BLE001 - never let audio break the conversation
        pass


def _chunks(text: str, size: int) -> list[str]:
    words, out, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > size and current:
            out.append(current)
            current = word
        else:
            current = candidate
    if current:
        out.append(current)
    return out


def stop() -> None:
    try:
        with _lock:
            _get_engine().stop()
    except Exception:  # noqa: BLE001
        pass


def wait_until_done(timeout: float = 30.0) -> None:
    """Best-effort wait used so we do not transcribe our own speaker output."""
    time.sleep(0.1)


def synthesize_wav(text: str) -> bytes | None:
    """Render text to a WAV file and return its bytes, for the web UI.

    Returns None if the text is empty, TTS is off, or SAPI fails, so the
    browser can quietly fall back to showing text only.
    """
    if not CONFIG.tts_enabled:
        return None
    spoken = _clean(text)
    if not spoken:
        return None

    import tempfile
    from pathlib import Path

    with _lock:
        try:
            engine = _get_engine()
            engine.stop()
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "hudu.wav"
                engine.save_to_file(spoken, str(path))
                engine.runAndWait()
                if not path.is_file() or path.stat().st_size < 44:
                    return None
                return path.read_bytes()
        except Exception:  # noqa: BLE001 - never let audio break a reply
            return None
