"""Microphone capture with energy-based voice activity detection."""

from __future__ import annotations

import contextlib
import io
import threading
import time
import wave
from typing import Callable, Iterator

import numpy as np
import sounddevice as sd

from .config import CONFIG


def _rms(block: np.ndarray) -> float:
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))


def list_input_devices() -> list[tuple[int, str]]:
    devices = []
    with contextlib.suppress(sd.PortAudioError):
        for idx, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                devices.append((idx, dev["name"]))
    return devices


def default_input_device() -> int | None:
    try:
        return sd.default.device[0]
    except (sd.PortAudioError, IndexError, TypeError):
        return None


def _noise_floor(seconds: float = 0.35) -> float:
    """Sample the room for a moment so we can set a relative speech threshold."""
    frames = int(CONFIG.sample_rate * seconds)
    try:
        data = sd.rec(frames, samplerate=CONFIG.sample_rate, channels=1, dtype="float32")
        sd.wait()
    except sd.PortAudioError:
        return 0.008
    level = _rms(data)
    return max(level, 0.002)


@contextlib.contextmanager
def _open_stream() -> Iterator[sd.Stream]:
    stream = sd.InputStream(
        samplerate=CONFIG.sample_rate,
        blocksize=int(CONFIG.sample_rate * CONFIG.block_ms / 1000),
        channels=1,
        dtype="float32",
        device=default_input_device(),
    )
    with stream:
        yield stream


def record_until_silence(
    max_seconds: int | None = None,
    on_level: Callable[[float], None] | None = None,
    stop_event: "threading.Event | None" = None,
) -> bytes:
    """Record from the mic until the speaker stops talking.

    Returns mono 16-bit PCM at 16 kHz. Recording ends on one of: a stretch of
    silence, the max_seconds cap, or stop_event being set (which is how the
    desktop app implements push-to-talk). Silence detection is relative to the
    room's noise floor so it works in both a quiet room and a noisy one.
    """
    max_seconds = max_seconds or CONFIG.max_record_seconds
    threshold = _noise_floor() * 3.2

    chunks: list[np.ndarray] = []
    blocks_per_second = 1000 / CONFIG.block_ms
    silence_blocks = int(CONFIG.silence_seconds * blocks_per_second)
    quiet_run = 0
    spoken = False
    started = time.time()

    with _open_stream() as stream:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            block, _ = stream.read(int(CONFIG.block_ms / 1000) * CONFIG.sample_rate)
            level = _rms(block)
            if on_level:
                on_level(level)

            if level > threshold:
                spoken = True
                quiet_run = 0
                chunks.append(block.copy())
            elif spoken:
                quiet_run += 1
                chunks.append(block.copy())
                if quiet_run >= silence_blocks:
                    break
            elif time.time() - started > max_seconds:
                break

            if time.time() - started > max_seconds:
                break

    if not chunks:
        return b""
    # Drop the leading/trailing near-silence to save tokens.
    samples = np.concatenate(chunks)
    return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def record_fixed(seconds: float) -> bytes:
    frames = int(CONFIG.sample_rate * seconds)
    with _open_stream() as stream:
        data, _ = stream.read(frames)
    return (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def write_wav(path: str, pcm: bytes, sample_rate: int | None = None) -> None:
    sample_rate = sample_rate or CONFIG.sample_rate
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)


def pcm_to_wav_bytes(pcm: bytes, sample_rate: int | None = None) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate or CONFIG.sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def wav_bytes_to_pcm(wav: bytes) -> bytes:
    """Strip the 44-byte canonical WAV header to get the raw PCM payload."""
    if len(wav) < 44:
        return b""
    if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        return wav
    return wav[44:]


def play_pcm(pcm: bytes) -> None:
    """Play recorded audio out loud (used to detect an echo of our own reply)."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size == 0:
        return
    with contextlib.suppress(sd.PortAudioError):
        sd.play(samples, CONFIG.sample_rate)
        sd.wait()
