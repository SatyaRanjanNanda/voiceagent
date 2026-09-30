"""Drive the WhatsApp desktop app with synthetic keystrokes.

The safety model is deliberate: a message is only ever typed into the composer.
It is never sent unless the user explicitly says yes afterwards. Saying no clears
the draft instead, so nothing is left half-written.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pyautogui as pag
import psutil

from . import apps

pag.FAILSAFE = True
pag.PAUSE = 0.04

LAUNCH_WAIT = 14.0
WINDOW_TITLE_HINTS = ("whatsapp",)
SEARCH_SETTLE = 0.9
TYPING_SETTLE = 0.5


@dataclass
class Draft:
    contact: str
    message: str
    typed_at: float
    attempts: int = 0


_STATE: dict[str, Draft | None] = {"draft": None}


def current_draft() -> Draft | None:
    draft = _STATE["draft"]
    if draft is None:
        return None
    if time.time() - draft.typed_at > 900:
        _STATE["draft"] = None
        return None
    return draft


def _clear_draft_state() -> None:
    _STATE["draft"] = None


# --- process / window helpers ---------------------------------------------


def _running() -> bool:
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if "whatsapp" in name:
            return True
    return False


def _wait_for_window(timeout: float = LAUNCH_WAIT) -> "object | None":
    import pygetwindow as gw

    deadline = time.time() + timeout
    best = None
    while time.time() < deadline:
        try:
            windows = [w for w in gw.getAllWindows() if w.title.strip()]
        except Exception:  # noqa: BLE001 - pygetwindow can throw on odd window states
            windows = []
        for window in windows:
            title = window.title.lower()
            if any(hint in title for hint in WINDOW_TITLE_HINTS):
                try:
                    if window.isMinimized:
                        window.restore()
                    if not window.isActive:
                        window.activate()
                except Exception:  # noqa: BLE001
                    pass
                return window
            if best is None and window.width > 400 and window.height > 400:
                best = window
        time.sleep(0.5)
    return best


def _ensure_running() -> tuple[bool, str]:
    if _running():
        return True, "WhatsApp is already open."
    result = apps.open_app("whatsapp")
    if not result.get("ok"):
        return False, result.get("message", "Could not launch WhatsApp.")
    return True, "Launched WhatsApp."


def _escape_for_clipboard_ok(message: str) -> str:
    return message.replace("\r\n", "\n").strip()


# --- actions ---------------------------------------------------------------


def type_message(contact: str, message: str) -> dict:
    """Open WhatsApp, open the chat, and type the message without sending it."""
    message = _escape_for_clipboard_ok(message)
    if not message:
        return {"ok": False, "message": "The message was empty, so nothing was typed."}

    started, note = _ensure_running()
    if not started:
        return {"ok": False, "message": note}

    window = _wait_for_window()
    if window is None:
        return {
            "ok": False,
            "message": "WhatsApp started but its window never appeared. Try opening it once manually.",
        }

    time.sleep(1.2)

    try:
        if contact:
            _open_chat(contact)
        else:
            _focus_composer_fallback()

        pag.click()
        time.sleep(0.2)
        pag.write(message, interval=0.012)
        time.sleep(TYPING_SETTLE)
    except pag.FailSafeException:
        return {
            "ok": False,
            "message": "Stopped: the mouse reached a screen corner (failsafe). Nothing was sent.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Typing failed: {exc}"}

    _STATE["draft"] = Draft(contact=contact, message=message, typed_at=time.time())
    where = f"to {contact}" if contact else "in the current chat"
    return {
        "ok": True,
        "awaiting_confirmation": True,
        "contact": contact,
        "message": message,
        "speech": (
            f"Typed your message {where}. It is sitting in the box, unsent. "
            "Say yes to send it, or no and I will clear it."
        ),
    }


def _open_chat(contact: str) -> None:
    """Use WhatsApp's own search box to jump to a contact or chat."""
    pag.hotkey("ctrl", "f")
    time.sleep(0.6)
    pag.hotkey("ctrl", "a")
    pag.press("backspace")
    time.sleep(0.2)
    pag.write(contact, interval=0.05)
    time.sleep(SEARCH_SETTLE)
    pag.press("enter")
    time.sleep(SEARCH_SETTLE)


def _focus_composer_fallback() -> None:
    """With no contact given, click the message composer at the window bottom."""
    try:
        import pygetwindow as gw

        window = gw.getActiveWindow()
        x = window.left + int(window.width * 0.5)
        y = window.top + int(window.height * 0.94)
        pag.click(x, y)
    except Exception:  # noqa: BLE001 - a stray click on the chat body is harmless
        pass
    time.sleep(0.4)


def confirm(send: bool) -> dict:
    """Honour the user's yes/no. No clears the draft without sending anything."""
    draft = current_draft()
    if draft is None:
        return {
            "ok": False,
            "message": "There is no message waiting to be sent, so nothing changed.",
        }

    if send:
        try:
            pag.press("enter")
            time.sleep(1.0)
        except pag.FailSafeException:
            return {
                "ok": False,
                "message": "Stopped by the mouse-corner failsafe. The message is still a draft.",
            }
        _clear_draft_state()
        where = f" to {draft.contact}" if draft.contact else ""
        return {"ok": True, "sent": True, "message": f"Sent the message{where}."}

    try:
        pag.hotkey("ctrl", "a")
        time.sleep(0.2)
        pag.press("backspace")
        time.sleep(0.4)
    except pag.FailSafeException:
        return {
            "ok": False,
            "message": "Stopped by the failsafe. Clear the WhatsApp box by hand if you want.",
        }
    _clear_draft_state()
    return {
        "ok": True,
        "sent": False,
        "cleared": True,
        "message": "Cleared the draft. Nothing was sent.",
    }


def close_app() -> dict:
    for proc in psutil.process_iter(["name"]):
        if "whatsapp" in (proc.info.get("name") or "").lower():
            try:
                proc.terminate()
            except psutil.Error:
                pass
    _clear_draft_state()
    return {"ok": True, "message": "Closed WhatsApp and discarded the draft."}


def status() -> dict:
    draft = current_draft()
    return {
        "ok": True,
        "running": _running(),
        "pending_draft": None if draft is None else {"contact": draft.contact, "message": draft.message},
    }


__all__ = ["type_message", "confirm", "close_app", "status", "current_draft"]
