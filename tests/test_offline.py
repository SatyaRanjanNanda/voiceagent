"""Offline tests for Hudu. No API key and no network required.

    python -m tests.test_offline
"""

from __future__ import annotations

import sys
import traceback

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  ok    {label}")
    else:
        FAILED.append(f"{label} {detail}".strip())
        print(f"  FAIL  {label} {detail}")


def test_tools_registered() -> None:
    from voiceagent import tools

    decls = {d.name for d in tools.declarations()}
    expected = {
        "open_app",
        "google_search",
        "play_youtube",
        "whatsapp_type",
        "whatsapp_confirm",
        "set_volume",
        "lock_computer",
    }
    check("all core tools declared", expected <= decls, f"missing {expected - decls}")


def test_schema_shapes() -> None:
    from google.genai import types

    from voiceagent import tools

    for decl in tools.declarations():
        params = decl.parameters
        is_object = params.type == types.Type.OBJECT
        check(
            f"schema {decl.name} is an object",
            is_object,
            f"got {params.type}",
        )
        props = params.properties or {}
        missing = [r for r in (params.required or []) if r not in props]
        check(f"schema {decl.name} required keys exist", not missing, f"missing {missing}")


def test_tool_dispatch_filters_bad_args() -> None:
    from voiceagent import tools

    result = tools.call("set_volume", {"steps": 3, "direction": "up", "bogus": "x"})
    check("unknown args are dropped not fatal", isinstance(result, dict))

    result = tools.call("does_not_exist", {})
    check("unknown tool reports cleanly", result.get("ok") is False)


def test_app_matching() -> None:
    from voiceagent.tools import apps

    check("app list is non-empty", len(apps.installed_apps()) > 10)
    for query, expected in (
        ("whatsapp", "whatsapp"),
        ("calc", "calc"),
        ("notepad", "notepad"),
    ):
        app, _ = apps.find_app(query)
        check(
            f"find_app({query!r}) resolves",
            app is not None and expected in app.target.lower() or (app and expected in app.name.lower()),
            f"got {app}",
        )

    app, suggestions = apps.find_app("definitely not an app zzqq")
    check("nonsense query returns no app", app is None)
    check("nonsense query still offers suggestions", isinstance(suggestions, list))


def test_wake_word_stripping() -> None:
    from voiceagent.config import CONFIG
    from voiceagent.stt import is_silence, strip_wake_word

    CONFIG.wake_word = "hudu"
    cases = [
        ("hudu what time is it", "what time is it", True),
        ("hey hudu, open spotify", "open spotify", True),
        ("HUDU!", "", True),
        ("what's the weather", "what's the weather", False),
    ]
    for text, expected, heard in cases:
        got, got_heard = strip_wake_word(text)
        check(f"strip_wake_word({text!r})", got == expected and got_heard == heard, f"got {got!r} {got_heard}")

    check("is_silence catches the sentinel", is_silence("SILENCE"))
    check("is_silence catches empty", is_silence("   "))
    check("is_silence catches fillers", is_silence("uhh umm"))
    check("is_silence keeps real speech", not is_silence("open notepad"))


def test_wake_word_survives_mishearing() -> None:
    """Speech recognition rarely spells the wake word correctly.

    Windows TTS pronounces "Hudu" as "hoo-doo", which comes back as "Hodu",
    "Hoodu", "Howdu" and friends. Missing those made the agent look deaf to its
    own name, so the variants have to count.
    """
    from voiceagent.config import CONFIG
    from voiceagent.stt import strip_wake_word

    CONFIG.wake_word = "hudu"
    misheard = [
        "Hodu, what is the capital of France?",
        "Hoodu open spotify",
        "Hudo open notepad",
        "hud what time is it",
        "OK Hudu turn on the lights",
    ]
    for text in misheard:
        remainder, heard = strip_wake_word(text)
        check(f"misheard wake word in {text!r}", heard, f"remainder={remainder!r}")
        check(f"  and leaves a usable request {text!r}", bool(remainder), "empty request")

    # The fuzzy pass must not start answering things nobody addressed to it.
    chatter = [
        "What is the capital of France?",
        "How are you today",
        "open spotify",
        "hello there",
        "hobby horse race",
        "how much is a dollar",
        "hi there buddy",
        "turn the lights off",
    ]
    for text in chatter:
        _remainder, heard = strip_wake_word(text)
        check(f"does not wake on {text!r}", not heard)


def test_strip_wake_word_return_order() -> None:
    """Guards a bug where the two return values were swapped.

    Callers unpack `request, heard_wake = strip_wake_word(...)`. With the
    order reversed, `request` silently became a bool and the very next line
    called is_silence(True), which raised and killed the whole turn.
    """
    from voiceagent.config import CONFIG
    from voiceagent.stt import is_silence, strip_wake_word

    CONFIG.wake_word = "hudu"
    request, heard = strip_wake_word("hudu open spotify")
    check("second value is a bool", isinstance(heard, bool), f"got {type(heard)}")
    check("first value is a str", isinstance(request, str), f"got {type(request)}")
    check("first value survives is_silence", isinstance(is_silence(request), bool))

    request, heard = strip_wake_word("just chatting about spotify")
    check("unaddressed request is still a str", isinstance(request, str))
    check("unaddressed request is not mistaken for silence", not is_silence(request))


def test_youtube_parsing() -> None:
    import json

    from voiceagent.tools import web

    sample = "\n".join(
        json.dumps(d)
        for d in (
            {"id": "abc123", "title": "First Song", "uploader": "Artist A", "duration": 215},
            {"id": "def456", "title": "Second Song", "uploader": "Artist B", "duration": 3725},
        )
    )
    videos = web._parse_flat_entries(sample)
    check("parses two videos", len(videos) == 2, f"got {len(videos)}")
    check("builds watch url", videos[0].url == "https://www.youtube.com/watch?v=abc123")
    check("formats short duration", videos[0].duration == "3:35", f"got {videos[0].duration}")
    check("formats long duration", videos[1].duration == "1:02:05", f"got {videos[1].duration}")
    check("label includes channel", "Artist A" in videos[0].label)
    check("skips junk lines", len(web._parse_flat_entries("not json\n\n")) == 0)


def test_url_detection() -> None:
    from voiceagent.tools import web

    check("detects https url", web.is_url("https://youtube.com/watch?v=1"))
    check("detects bare www", web.is_url("www.google.com"))
    check("rejects plain words", not web.is_url("lofi beats"))


def test_whatsapp_state_machine() -> None:
    from voiceagent.tools import whatsapp

    whatsapp._STATE["draft"] = None
    check("no draft at start", whatsapp.current_draft() is None)

    result = whatsapp.confirm(send=True)
    check("confirm with no draft is a no-op", result.get("ok") is False)

    from voiceagent.tools.whatsapp import Draft

    whatsapp._STATE["draft"] = Draft(contact="Alice", message="hi", typed_at=0)
    check("stale draft is expired and cleared", whatsapp.current_draft() is None)

    import time as _time

    whatsapp._STATE["draft"] = Draft(contact="Alice", message="hi", typed_at=_time.time())
    draft = whatsapp.current_draft()
    check("fresh draft is visible", draft is not None and draft.contact == "Alice")

    whatsapp._STATE["draft"] = None
    empty = whatsapp.type_message("Alice", "   ")
    check("empty message is rejected before typing", empty.get("ok") is False)
    check("rejected message left no draft", whatsapp.current_draft() is None)

    whatsapp._STATE["draft"] = None


def test_web_queries() -> None:
    from urllib.parse import parse_qs, urlparse

    from voiceagent.tools import web

    url = web.youtube_url_for("lofi hip hop")
    check(
        "youtube search url encodes query",
        parse_qs(urlparse(url).query)["search_query"] == ["lofi hip hop"],
    )


def test_result_slimming() -> None:
    from voiceagent.llm import _parse_args, _slim

    check("parses dict args", _parse_args({"a": 1}) == {"a": 1})
    check("parses json string args", _parse_args('{"a": 1}') == {"a": 1})
    check("survives junk args", isinstance(_parse_args(None), dict))

    slim = _slim({"msg": "x" * 5000, "items": list(range(100))})
    check("long strings truncated", len(slim["msg"]) < 5000)
    check("long lists truncated", len(slim["items"]) == 41)


def test_agent_system_prompt_names_hudu() -> None:
    from voiceagent.llm import PERSONA
    from voiceagent.config import CONFIG

    persona = PERSONA.format(name=CONFIG.name)
    check("persona is named", CONFIG.name in persona, f"name={CONFIG.name}")
    check("persona forbids markdown", "no markdown" in persona.lower())
    check("persona has whatsapp protocol", "WHATSAPP PROTOCOL" in persona)


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    print(f"Running {len(tests)} offline tests\n")
    for test in tests:
        print(f"{test.__name__}")
        try:
            test()
        except Exception:  # noqa: BLE001
            FAILED.append(test.__name__)
            traceback.print_exc()
        print("")

    print("=" * 60)
    print(f"passed {len(PASSED)}   failed {len(FAILED)}")
    for failure in FAILED:
        print(f"  FAILED: {failure}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
