#!/usr/bin/env python
"""Entry point for Hudu, the local voice assistant.

    python run.py --gui      launch the desktop app
    python run.py            voice mode, push to talk with Space
    python run.py --text     typed mode, for testing without a microphone
    python run.py --devices  list microphones and exit
    python run.py --voices   list spoken-reply voices and exit
    python run.py --check    verify the setup and exit
"""

from __future__ import annotations

import argparse
import sys
import time

from voiceagent import audio, llm, stt, tts
from voiceagent.config import CONFIG

BAR = "─" * 62


def say(text: str) -> None:
    print(text, flush=True)


def banner() -> None:
    say("")
    say(BAR)
    say(f"  {CONFIG.name} is listening. Model: {CONFIG.model} | STT: {CONFIG.stt_backend}")
    say(BAR)


def check_audio() -> bool:
    devices = audio.list_input_devices()
    if not devices:
        say("No microphone was found.")
        say("Windows microphone privacy: Settings > Privacy > Microphone > Allow apps.")
        return False
    active = audio.default_input_device()
    for idx, name in devices:
        marker = "  <- in use" if idx == active else ""
        say(f"  mic {idx}: {name}{marker}")
    return True


def check_tts() -> None:
    if not CONFIG.tts_enabled:
        return
    voices = tts.list_voices()
    if not voices:
        say("No SAPI voices found, so Hudu will only print replies.")
        CONFIG.tts_enabled = False
        return
    tts.select_voice(CONFIG.tts_voice_index)
    say(f"  voice: {voices[min(CONFIG.tts_voice_index, len(voices) - 1)]}")


# --- voice mode -------------------------------------------------------------


def _drain_keys() -> None:
    """Swallow buffered keystrokes so held keys do not queue up extra turns."""
    import msvcrt

    while msvcrt.kbhit():
        msvcrt.getwch()


def _wait_for_trigger() -> str | None:
    """Block until the user presses a key. Returns the key, or None to quit.

    Uses msvcrt rather than a global hotkey library so Hudu works in a normal
    terminal, needs no administrator rights, and cannot steal keys from other
    windows while the user is typing elsewhere.
    """
    import msvcrt

    while True:
        if msvcrt.kbhit():
            char = msvcrt.getwch()
            if char in {"\x1b", "q", "Q"}:  # Esc or q
                return None
            if char == " ":
                return "space"
        else:
            time.sleep(0.03)


def run_voice(agent: llm.Agent) -> None:
    banner()
    check_audio()
    check_tts()

    wake = CONFIG.wake_word or CONFIG.name.lower()
    say("")
    say(f"  Press SPACE and hold it while you talk. Release to send.")
    say(f"  Or just speak and start with '{wake}'.")
    say("  Q or ESC quits.")
    say("")

    while True:
        say("  [press SPACE to talk]")
        if _wait_for_trigger() is None:
            say("  bye.")
            return

        pcm = audio.record_until_silence()
        _drain_keys()
        tts.stop()

        if len(pcm) < CONFIG.sample_rate // 4:  # under a quarter second
            continue

        try:
            transcript = stt.transcribe(audio.pcm_to_wav_bytes(pcm))
        except stt.TranscriptionError as exc:
            say(f"  could not hear that: {exc}")
            continue

        if stt.is_silence(transcript):
            say("  (nothing heard)")
            continue

        request, heard_wake = stt.strip_wake_word(transcript)
        said = f"  you: {transcript}"

        if heard_wake:
            say(said)
        elif CONFIG.wake_word_required:
            # Chatter that was not addressed to Hudu. Ignore it.
            continue
        else:
            say(said)

        if stt.is_silence(request):
            continue

        say(f"  {CONFIG.name.lower()}: thinking...")
        try:
            reply = speak_reply(agent, request)
        except llm.AgentError as exc:
            say(f"  error: {exc}")
            continue
        finally:
            tts.stop()

        for step in agent.last_tool_trace:
            say(f"    · {step}")
        say(f"  {CONFIG.name.lower()}: {reply}")
        say("")


def speak_reply(agent: llm.Agent, request: str) -> str:
    chunks: list[str] = []
    for chunk in agent.respond(request):
        chunks.append(chunk)
        tts.speak(chunk, interrupt=True)
    return " ".join(c.strip() for c in chunks if c.strip()) or "Done."


# --- text mode --------------------------------------------------------------


def run_text(agent: llm.Agent) -> None:
    banner()
    say("  Typed mode. Type a request, or 'quit' to exit.")
    say("")
    while True:
        try:
            line = input("  you > ").strip()
        except (EOFError, KeyboardInterrupt):
            say("")
            return
        if not line:
            continue
        if line.lower() in {"quit", "exit", "q"}:
            return
        try:
            reply = " ".join(agent.respond(line))
        except llm.AgentError as exc:
            say(f"  error: {exc}")
            continue
        for step in agent.last_tool_trace:
            say(f"    · {step}")
        say(f"  {CONFIG.name.lower()} > {reply}")
        say("")


# --- main -------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(prog="hudu", description="Hudu voice assistant")
    parser.add_argument("--text", action="store_true", help="typed mode, no microphone")
    parser.add_argument("--devices", action="store_true", help="list audio devices and exit")
    parser.add_argument("--voices", action="store_true", help="list TTS voices and exit")
    parser.add_argument("--check", action="store_true", help="verify setup and exit")
    parser.add_argument("--gui", action="store_true", help="launch the desktop app")
    args = parser.parse_args()

    if args.gui:
        from voiceagent.desktop.app import main as gui_main

        return gui_main()

    if args.devices:
        say("Input devices:")
        for idx, name in audio.list_input_devices():
            say(f"  {idx}: {name}")
        return 0

    if args.voices:
        voices = tts.list_voices()
        if not voices:
            say("No SAPI voices are installed.")
            return 1
        say("TTS voices (set TTS_VOICE_INDEX in .env):")
        for idx, name in enumerate(voices):
            marker = "  <- current" if idx == CONFIG.tts_voice_index else ""
            say(f"  {idx}: {name}{marker}")
        return 0

    if args.check:
        return run_check()

    CONFIG.require_api_key()

    if not args.text and not check_audio():
        return 1
    check_tts()

    try:
        agent = llm.Agent()
    except Exception as exc:  # noqa: BLE001
        say(f"Could not start {CONFIG.name}: {exc}")
        return 1

    if args.text:
        run_text(agent)
    else:
        try:
            run_voice(agent)
        except KeyboardInterrupt:
            say("")
    return 0


def run_check() -> int:
    say("Hudu setup check")
    say(BAR)
    ok = True

    if CONFIG.api_key:
        say(f"  [ok]   GOOGLE_API_KEY found ({CONFIG.api_key[:6]}...)")
    else:
        say("  [FAIL] GOOGLE_API_KEY missing. Copy .env.example to .env.")
        ok = False

    say(f"  [..]   model: {CONFIG.model}")

    try:
        import google.genai  # noqa: F401

        say("  [ok]   google-genai installed")
    except ImportError:
        say("  [FAIL] google-genai not installed. Run: pip install -r requirements.txt")
        ok = False

    if CONFIG.stt_backend == "cloud" and not (
        CONFIG.gcp_credentials or CONFIG.gcp_project
    ):
        say("  [FAIL] STT_BACKEND=cloud but no service-account credentials are set.")
        ok = False
    else:
        say(f"  [ok]   stt backend: {CONFIG.stt_backend}")

    mics = audio.list_input_devices()
    if mics:
        say(f"  [ok]   {len(mics)} input device(s): {mics[0][1]}")
    else:
        say("  [warn] no microphone found; use --text for typed mode")

    try:
        from voiceagent import tools

        say(f"  [ok]   {len(tools.declarations())} tools registered")
    except Exception as exc:  # noqa: BLE001
        say(f"  [FAIL] tools failed to load: {exc}")
        ok = False

    say(BAR)
    say("Ready." if ok else "Fix the [FAIL] lines above, then try again.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
