"""Small Windows system controls the agent can reach for."""

from __future__ import annotations

import ctypes
import os
import subprocess
import time

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

user32 = getattr(ctypes, "windll", None) and ctypes.windll.user32


def _tap(vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)
    time.sleep(0.04)


def _media(vk: int, steps: int) -> None:
    for _ in range(max(1, min(steps, 25))):
        _tap(vk)
    time.sleep(0.2)


def set_volume(steps: int = 5, direction: str = "up") -> dict:
    if user32 is None:
        return {"ok": False, "message": "Volume control is Windows-only."}
    vk = VK_VOLUME_UP if direction == "up" else VK_VOLUME_DOWN
    _media(vk, steps)
    return {"ok": True, "message": f"Volume {direction} {steps} step(s)."}


def toggle_mute() -> dict:
    if user32 is None:
        return {"ok": False, "message": "Volume control is Windows-only."}
    _tap(VK_VOLUME_MUTE)
    return {"ok": True, "message": "Toggled mute."}


def lock() -> dict:
    subprocess.Popen("rundll32.exe user32.dll,LockWorkStation")  # noqa: S603, S607
    return {"ok": True, "message": "Locked the computer."}


def screenshot(path: str | None = None) -> dict:
    import os as _os
    import tempfile

    if not path:
        path = _os.path.join(tempfile.gettempdir(), f"voiceagent-{int(time.time())}.png")
    image = pag.screenshot()
    image.save(path)
    return {"ok": True, "path": path, "message": f"Saved a screenshot to {path}"}


def shutdown(delay_seconds: int = 30) -> dict:
    subprocess.Popen(  # noqa: S603
        ["shutdown", "/s", "/t", str(max(0, delay_seconds))],
        shell=False,
    )
    return {
        "ok": True,
        "message": f"Shutting down in {delay_seconds} seconds. Run 'shutdown /a' to cancel.",
    }


def cancel_shutdown() -> dict:
    proc = subprocess.run(  # noqa: S603
        ["shutdown", "/a"], capture_output=True, text=True, shell=False, check=False
    )
    return {
        "ok": proc.returncode == 0,
        "message": "Shutdown cancelled."
        if proc.returncode == 0
        else "There was no shutdown to cancel.",
    }


def open_folder(path: str = ".") -> dict:
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        return {"ok": False, "message": f"There is nothing at {path}."}
    os.startfile(path)  # noqa: S606
    return {"ok": True, "message": f"Opened {path}"}
