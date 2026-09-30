"""Launch desktop applications by fuzzy-matching their name."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import process

# Deliberately high: launching the wrong app is worse than asking what they meant.
# Common short names are all reachable through the ALIAS table below, so this does
# not hurt "wa", "calc", or "chrome".
MATCH_CUTOFF = 75

# Apps people ask for constantly, so a miss never costs a second lookup.
ALIASES: dict[str, str] = {
    "whatsapp": "WhatsApp",
    "wa": "WhatsApp",
    "notepad": "notepad",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "settings": "ms-settings:",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "brave": "brave.exe",
    "vs code": "code",
    "visual studio code": "code",
    "vscode": "code",
    "spotify": "Spotify.exe",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "task manager": "taskmgr",
    "control panel": "control",
    "snipping tool": "snippingtool",
    "camera": "microsoft.windows.camera:",
    "clock": "ms-clock:",
    "store": "ms-windows-store:",
    "photos": "microsoft.windows.photos:",
    "youtube": "https://www.youtube.com",
    "whatsapp web": "https://web.whatsapp.com",
}

_START_MENU = (
    rf"C:\Users\{os.environ.get('USERNAME', '')}\AppData\Roaming\Microsoft\Windows\Start Menu\Programs",
    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
)


@dataclass(frozen=True)
class App:
    name: str
    target: str


def _start_menu_shortcuts() -> list[App]:
    found: list[App] = []
    for root in _START_MENU:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                if filename.lower().endswith((".lnk", ".url", ".exe")):
                    label = os.path.splitext(filename)[0]
                    found.append(App(label, os.path.join(dirpath, filename)))
    return sorted(found, key=lambda a: a.name.lower())


@lru_cache(maxsize=1)
def installed_apps() -> list[App]:
    apps: dict[str, App] = {}

    for alias, target in ALIASES.items():
        apps.setdefault(alias.lower(), App(alias.title(), target))

    program_dirs = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    for base in program_dirs:
        if not os.path.isdir(base):
            continue
        for entry in os.scandir(base):
            if not entry.is_dir():
                continue
            top = entry.name
            apps.setdefault(top.lower(), App(top, entry.path))
            inner = os.path.join(entry.path, top)
            if os.path.isdir(inner):
                try:
                    for sub in os.scandir(inner):
                        if sub.is_dir():
                            apps.setdefault(sub.name.lower(), App(sub.name, sub.path))
                        elif sub.name.lower().endswith(".exe"):
                            apps.setdefault(
                                os.path.splitext(sub.name)[0].lower(),
                                App(os.path.splitext(sub.name)[0], sub.path),
                            )
                except OSError:
                    pass

    for shortcut in _start_menu_shortcuts():
        apps.setdefault(shortcut.name.lower(), shortcut)

    return sorted(apps.values(), key=lambda a: a.name.lower())


def find_app(query: str) -> tuple[App | None, list[tuple[str, float]]]:
    query = query.strip()
    if not query:
        return None, []
    apps = installed_apps()
    names = [app.name for app in apps]

    exact = next((a for a in apps if a.name.lower() == query.lower()), None)
    if exact:
        return exact, []

    scores = process.extract(query, names, limit=5, score_cutoff=MATCH_CUTOFF)
    suggestions = [(name, score) for name, score, _ in scores]
    if not scores:
        return None, suggestions
    return apps[names.index(scores[0][0])], suggestions


def _launch(target: str) -> tuple[bool, str]:
    if target.startswith("http"):
        return _launch_url(target)
    if ":" in target and not os.path.exists(target) and "://" not in target:
        # A shell namespace such as ms-settings: or calculator:.
        os.startfile(target)  # noqa: S606
        return True, f"opened {target}"
    if not os.path.exists(target):
        return False, f"target not found: {target}"
    if os.path.isdir(target):
        os.startfile(target)  # noqa: S606
        return True, f"opened folder {target}"
    if target.lower().endswith(".lnk"):
        os.startfile(target)  # noqa: S606
        return True, f"opened {os.path.basename(target)}"
    subprocess.Popen(  # noqa: S603
        [target],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    return True, f"launched {os.path.basename(target)}"


def _launch_url(url: str) -> tuple[bool, str]:
    import webbrowser

    if webbrowser.open(url):
        return True, f"opened {url}"
    os.startfile(url)  # noqa: S606
    return True, f"opened {url}"


def open_app(name: str) -> dict:
    app, suggestions = find_app(name)
    if app is None:
        hint = ""
        if suggestions:
            hint = " Did you mean: " + ", ".join(s for s, _ in suggestions[:3]) + "?"
        return {
            "ok": False,
            "message": f"I could not find an app called {name!r}.{hint} "
            f"I can also search the web for it if you want.",
            "suggestions": [s for s, _ in suggestions[:3]],
        }
    try:
        _ok, detail = _launch(app.target)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Failed to open {app.name}: {exc}"}
    return {"ok": True, "app": app.name, "message": f"Opened {app.name}. {detail}"}


def app_names(limit: int = 400) -> list[str]:
    return [a.name for a in installed_apps()][:limit]


if __name__ == "__main__":  # manual check:  python -m voiceagent.tools.apps
    print(f"{len(installed_apps())} apps discovered")
    for name in app_names(25):
        print(" -", name)
    print()
    for query in ("whatsapp", "chrome", "calc", "spotify"):
        app, sug = find_app(query)
        print(f"{query!r} -> {app.name if app else None} {app.target if app else sug}")
