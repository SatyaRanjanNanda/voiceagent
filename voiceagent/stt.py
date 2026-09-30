"""Speech-to-text with two interchangeable backends.

gemini : ships the mic audio straight to Gemini. Works with nothing but the
         GOOGLE_API_KEY, so it is the default.
cloud  : Google Cloud Speech-to-Text. More accurate on noisy audio, but it
         authenticates with a service account rather than an API key, so it
         needs GOOGLE_APPLICATION_CREDENTIALS to be set.
"""

from __future__ import annotations

import re
import time

from rapidfuzz import fuzz

from .config import CONFIG

_SYSTEM = (
    "Transcribe the user's speech from the audio. Return ONLY the spoken words, "
    "nothing else. No preamble, no quotes, no punctuation fixes, no translation. "
    "If the audio contains no speech, return the single word: SILENCE"
)


class TranscriptionError(RuntimeError):
    pass


def _transcribe_gemini(wav_bytes: bytes) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=CONFIG.api_key)
    config = types.GenerateContentConfig(
        temperature=0.0,
        max_output_tokens=512,
        # Transcription needs no deliberation. Skipping it is faster and
        # cheaper, and stops reasoning tokens from eating the output
        # budget and returning an empty transcript.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    contents = [
        types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"),
        _SYSTEM,
    ]

    # Same model failover as the chat loop: one throttled model should not
    # stop you being heard.
    problems: list[str] = []
    for model in CONFIG.model_chain():
        for attempt in range(1, 3):
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                text = (response.text or "").strip()
                if text:
                    return text
                problems.append(f"{model}: empty transcript")
                break
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{model}: {str(exc)[:140]}")
                text = str(exc).lower()
                fatal = any(
                    code in text
                    for code in ("api key not valid", "permission_denied", "404")
                )
                if fatal or attempt == 2:
                    break
                time.sleep(1.0 * attempt)

    from .llm import diagnose

    raise TranscriptionError(diagnose(problems))


class CloudTranscriber:
    """Lazy wrapper so the cloud SDK stays an optional dependency."""

    _client = None

    @classmethod
    def _get_client(cls):
        if cls._client is not None:
            return cls._client
        try:
            from google.cloud import speech
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise TranscriptionError(
                "STT_BACKEND=cloud needs the Google Cloud Speech SDK.\n"
                "Install it with:  pip install google-cloud-speech"
            ) from exc

        if not CONFIG.gcp_credentials and not CONFIG.gcp_project:
            raise TranscriptionError(
                "STT_BACKEND=cloud is selected but no credentials are configured.\n"
                "Either set GOOGLE_APPLICATION_CREDENTIALS in .env, or switch\n"
                "STT_BACKEND back to 'gemini' in .env."
            )
        cls._client = speech.SpeechClient()
        return cls._client

    def transcribe(self, wav_bytes: bytes) -> str:
        from google.cloud import speech

        client = self._get_client()
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.WAV,
            sample_rate_hertz=CONFIG.sample_rate,
            language_code="en-US",
            enable_automatic_punctuation=True,
        )
        audio = speech.RecognitionAudio(content=wav_bytes)
        response = client.recognize(config=config, audio=audio)
        return " ".join(result.alternatives[0].transcript for result in response.results).strip()


def transcribe(wav_bytes: bytes) -> str:
    if CONFIG.stt_backend == "cloud":
        return CloudTranscriber().transcribe(wav_bytes)
    if not wav_bytes:
        return ""
    try:
        return _transcribe_gemini(wav_bytes)
    except TranscriptionError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any SDK failure as text
        raise TranscriptionError(f"Gemini transcription failed: {exc}") from exc


_FILLER = re.compile(r"\b(um+|uh+|erm+|hmm+)\b", re.IGNORECASE)
# Speech recognition rarely returns the wake word as it was spelled. Windows
# TTS says "Hudu" as "hoo-doo", which comes back as "Hodu", "Hoodu", "Howdu",
# and half a dozen other spellings. Anything close enough to the real thing
# counts as the wake word, otherwise the agent looks deaf to its own name.
_WAKE_SIMILARITY = 66
_MAX_WAKE_LEAD_WORDS = 3


def is_silence(text: str) -> bool:
    cleaned = _FILLER.sub("", text).strip(" .!?,:;-—…\"'")
    return not cleaned or cleaned.upper() == "SILENCE"


def _wake_word_said(phrase: str) -> tuple[str, bool]:
    """Check the opening words for the wake word. Returns (remainder, heard)."""
    wake = CONFIG.wake_word
    if not wake:
        return phrase.strip(), True

    words = phrase.split()
    if not words:
        return phrase.strip(), False

    # Exact-ish forms first: "hudu", "hey hudu", "hudu,".
    pattern = re.compile(
        rf"^\s*(?:hey\s+|ok\s+|okay\s+|yo\s+)?{re.escape(wake)}\b[\s,.:;!?-]*",
        re.IGNORECASE,
    )
    if pattern.match(phrase):
        return pattern.sub("", phrase, count=1).strip(), True

    # Then a fuzzy pass over just the first few words, so a misheard spelling
    # still wakes it without matching unrelated chatter.
    for index in range(min(_MAX_WAKE_LEAD_WORDS, len(words))):
        candidate = words[index].strip(".,!?;:")
        if len(candidate) < 3:
            continue
        if fuzz.ratio(candidate.lower(), wake.lower()) >= _WAKE_SIMILARITY:
            remainder = " ".join(words[:index] + words[index + 1 :])
            return remainder.strip(), True

    return phrase.strip(), False


def strip_wake_word(text: str) -> tuple[str, bool]:
    """Remove a leading wake word. Returns (remaining text, wake word heard)."""
    return _wake_word_said(text)
