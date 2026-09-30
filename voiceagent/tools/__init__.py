"""Tool registry: the bridge between Gemini function calling and Python."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from google.genai import types

from . import apps, system, web, whatsapp

Handler = Callable[..., dict]
_PARAM = tuple[str, "types.Schema"]
_REGISTRY: dict[str, Handler] = {}


def tool(
    *,
    name: str,
    description: str,
    parameters: list[_PARAM] | None = None,
    required: list[str] | None = None,
) -> Callable[[Handler], Handler]:
    params = parameters or []

    def decorator(fn: Handler) -> Handler:
        _REGISTRY[name] = fn
        fn.declaration = types.FunctionDeclaration(  # type: ignore[attr-defined]
            name=name,
            description=description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={key: schema for key, schema in params},
                required=required or [],
            ),
        )
        return fn

    return decorator


def _string(key: str, desc: str) -> _PARAM:
    return key, types.Schema(type=types.Type.STRING, description=desc)


def _integer(key: str, desc: str) -> _PARAM:
    return key, types.Schema(type=types.Type.INTEGER, description=desc)


def _boolean(key: str, desc: str) -> _PARAM:
    return key, types.Schema(type=types.Type.BOOLEAN, description=desc)


def _enum(key: str, desc: str, options: list[str]) -> _PARAM:
    return key, types.Schema(type=types.Type.STRING, enum=options, description=desc)


# --- apps -------------------------------------------------------------------


@tool(
    name="open_app",
    description=(
        "Launch a desktop application by name, e.g. 'spotify', 'notepad', 'chrome', "
        "'task manager'. Use this whenever the user wants to open, run, or start a program."
    ),
    parameters=[_string("name", "The name of the app to launch, as the user said it.")],
    required=["name"],
)
def open_app(name: str) -> dict:
    return apps.open_app(name)


@tool(
    name="list_apps",
    description="List the applications installed on this computer. Use only if the user asks what is available.",
    parameters=[],
)
def list_apps() -> dict:
    names = apps.app_names()
    return {"ok": True, "count": len(names), "apps": names}


# --- web --------------------------------------------------------------------


@tool(
    name="google_search",
    description=(
        "Search the web with Google and open the results in the browser. Use this for "
        "anything that needs live facts: news, prices, weather, scores, docs, or when the "
        "user says 'search for', 'look up', or 'google'."
    ),
    parameters=[_string("query", "The search query.")],
    required=["query"],
)
def google_search(query: str) -> dict:
    return {"ok": True, "url": web.google_search(query), "message": f"Searched Google for {query!r}."}


@tool(
    name="open_url",
    description="Open a specific web address in the default browser.",
    parameters=[_string("url", "The full URL, including https://")],
    required=["url"],
)
def open_url(url: str) -> dict:
    return {"ok": True, "url": web.open_url(url), "message": f"Opened {url}"}


# --- youtube ----------------------------------------------------------------


@tool(
    name="play_youtube",
    description=(
        "Find a video or song on YouTube and start playing it. Use this for 'play X on "
        "YouTube', 'put on X', or when the user names a song, artist, or video. Handles "
        "songs, podcasts, lectures, and vlogs."
    ),
    parameters=[
        _string("query", "What to play: a song, artist, video title, topic, or a YouTube URL."),
        _boolean(
            "music",
            "True for music (picks the best audio upload), false for video (the normal result). Default false.",
        ),
    ],
    required=["query"],
)
def play_youtube(query: str, music: bool = False) -> dict:
    return _play_on_youtube(query, music=music)


@tool(
    name="search_youtube",
    description=(
        "Look up YouTube results WITHOUT playing anything. Use when the user wants to browse "
        "or see options rather than start playback."
    ),
    parameters=[_string("query", "What to search YouTube for.")],
    required=["query"],
)
def search_youtube(query: str) -> dict:
    return _search_on_youtube(query)


def _search_on_youtube(query: str, music: bool = False) -> dict:
    try:
        if web.is_url(query):
            url = query if query.startswith("http") else f"https://{query}"
            results = [web.Video(title=query, url=url, channel="", duration="", source="url")]
        elif music:
            results = web.spotify_search(query, limit=5)
        else:
            results = web.youtube_search(query, limit=5)
    except FileNotFoundError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001 - network or yt-dlp failure
        return {
            "ok": False,
            "message": f"YouTube lookup failed: {exc}. I can open the YouTube results page instead.",
        }

    if not results:
        return {"ok": False, "message": f"I could not find anything on YouTube for {query!r}."}

    return {
        "ok": True,
        "results": [
            {"title": v.title, "channel": v.channel, "duration": v.duration, "url": v.url}
            for v in results
        ],
        "message": "\n".join(f"{i + 1}. {v.label} -> {v.url}" for i, v in enumerate(results)),
    }


def _play_on_youtube(query: str, music: bool = False) -> dict:
    found = _search_on_youtube(query, music=music)
    if not found.get("ok"):
        web.open_url(web.youtube_url_for(query))
        return {
            "ok": True,
            "fallback": True,
            "message": f"Could not resolve {query!r} to one video, so I opened the YouTube results page.",
        }

    top = found["results"][0]
    web.play_in_browser(top["url"])
    detail = f" by {top['channel']}" if top.get("channel") else ""
    return {"ok": True, "playing": top, "message": f"Playing {top['title']}{detail} on YouTube."}


# --- whatsapp ---------------------------------------------------------------


@tool(
    name="whatsapp_type",
    description=(
        "Open WhatsApp and TYPE a message into the chat, but never send it. Use this for "
        "'text Alice saying I will be late', 'message mom hello'. After this tool runs you "
        "MUST ask the user whether to send, then honour the answer with whatsapp_confirm."
    ),
    parameters=[
        _string(
            "contact",
            "The contact or chat name to open, e.g. 'Alice', 'Mum', 'work group'. "
            "Pass an empty string to use whatever chat is already open.",
        ),
        _string("message", "The exact message text to type."),
    ],
    required=["message"],
)
def whatsapp_type(contact: str, message: str) -> dict:
    return whatsapp.type_message(contact, message)


@tool(
    name="whatsapp_confirm",
    description=(
        "Settle a WhatsApp message that was typed but not sent. Call with send=true when the "
        "user says yes, or send=false when they say no, change their mind, or want it deleted."
    ),
    parameters=[_boolean("send", "True to press send. False to clear the draft without sending.")],
    required=["send"],
)
def whatsapp_confirm(send: bool) -> dict:
    return whatsapp.confirm(send=bool(send))


@tool(
    name="whatsapp_status",
    description="Check whether WhatsApp is open and whether a message is waiting to be sent.",
    parameters=[],
)
def whatsapp_status() -> dict:
    return whatsapp.status()


# --- system -----------------------------------------------------------------


@tool(
    name="set_volume",
    description="Turn the system volume up or down.",
    parameters=[
        _integer("steps", "How many steps. 1 step is roughly 2 percent. Keep it between 1 and 25."),
        _enum("direction", "Which way to move the volume.", ["up", "down"]),
    ],
    required=["steps", "direction"],
)
def set_volume(steps: int, direction: str) -> dict:
    return system.set_volume(steps=steps, direction=direction)


@tool(
    name="toggle_mute",
    description="Mute or unmute the system audio.",
    parameters=[],
)
def toggle_mute() -> dict:
    return system.toggle_mute()


@tool(
    name="lock_computer",
    description="Lock the Windows desktop. Only use this when the user explicitly asks to lock it.",
    parameters=[],
)
def lock_computer() -> dict:
    return system.lock()


@tool(
    name="screenshot",
    description="Capture the screen to a PNG file and report where it was saved.",
    parameters=[],
)
def screenshot() -> dict:
    return system.screenshot()


@tool(
    name="shutdown_computer",
    description=(
        "Shut Windows down after a delay. Only for an explicit shutdown request, and warn the "
        "user first so they have time to cancel it."
    ),
    parameters=[_integer("delay_seconds", "Seconds to wait before shutting down. Default 60.")],
)
def shutdown_computer(delay_seconds: int = 60) -> dict:
    return system.shutdown(delay_seconds=delay_seconds)


# --- registry ---------------------------------------------------------------


def declarations() -> list[types.FunctionDeclaration]:
    return [fn.declaration for fn in _REGISTRY.values()]  # type: ignore[attr-defined]


def call(name: str, args: dict[str, Any]) -> dict:
    handler = _REGISTRY.get(name)
    if handler is None:
        return {"ok": False, "message": f"Unknown tool {name!r}."}

    signature = inspect.signature(handler)
    accepted = {k: v for k, v in args.items() if k in signature.parameters}
    dropped = sorted(set(args) - set(accepted))
    try:
        result = handler(**accepted)
    except TypeError as exc:
        return {"ok": False, "message": f"Bad arguments for {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - a broken tool must not kill the agent
        return {"ok": False, "message": f"{name} failed: {exc}"}
    if dropped:
        result.setdefault("note", f"Ignored unexpected argument(s): {', '.join(dropped)}.")
    return result
