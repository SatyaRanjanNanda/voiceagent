"""Web search and YouTube playback."""

from __future__ import annotations

import shutil
import subprocess
import webbrowser
from dataclasses import dataclass
from urllib.parse import quote_plus, urlencode

DEFAULT_BROWSER = None


@dataclass
class Video:
    title: str
    url: str
    channel: str
    duration: str
    source: str

    @property
    def label(self) -> str:
        bits = [self.title]
        if self.channel:
            bits.append(f"by {self.channel}")
        if self.duration:
            bits.append(self.duration)
        return ", ".join(bits)


def google_search(query: str) -> str:
    url = "https://www.google.com/search?" + urlencode({"q": query})
    webbrowser.open(url)
    return url


def duckduckgo(query: str) -> str:
    url = "https://duckduckgo.com/?" + urlencode({"q": query})
    webbrowser.open(url)
    return url


def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return url


def _yt_dlp() -> str:
    found = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if found:
        return found

    # Fall back to a copy installed next to the interpreter, which is the case
    # whenever yt-dlp was pip-installed into the same virtualenv as this script.
    import sys
    from pathlib import Path

    name = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
    scripts_dir = Path(sys.executable).resolve().parent
    for candidate in (scripts_dir / name, scripts_dir / "Scripts" / name):
        if candidate.is_file():
            return str(candidate)

    raise FileNotFoundError(
        "yt-dlp was not found. Install it with:  pip install yt-dlp"
    )


def _run(args: list[str], timeout: int = 45) -> str:
    proc = subprocess.run(  # noqa: S603
        [_yt_dlp(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "yt-dlp failed").strip()[-400:])
    return proc.stdout


def _parse_flat_entries(raw: str) -> list[Video]:
    import json

    videos: list[Video] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not item.get("id") or not item.get("title"):
            continue
        videos.append(
            Video(
                title=item["title"],
                url=f"https://www.youtube.com/watch?v={item['id']}",
                channel=item.get("uploader") or item.get("channel") or "",
                duration=_format_duration(item.get("duration")),
                source="youtube",
            )
        )
    return videos


def _format_duration(seconds) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def youtube_search(query: str, limit: int = 5) -> list[Video]:
    args = [
        f"ytsearch{limit}:{query}",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        "--skip-download",
    ]
    return _parse_flat_entries(_run(args))


def spotify_search(query: str, limit: int = 5) -> list[Video]:
    args = [
        f"ytsearch{limit}:{query} audio",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        "--skip-download",
    ]
    return _parse_flat_entries(_run(args))


def is_url(text: str) -> bool:
    return text.strip().lower().startswith(("http://", "https://", "www."))


def direct_media_url(url: str) -> str:
    """Resolve a YouTube page URL to its playable stream."""
    args = [
        url,
        "--no-playlist",
        "-f",
        "bestaudio/best",
        "--get-url",
        "--no-warnings",
    ]
    return _run(args, timeout=60).strip().splitlines()[-1]


def play_in_browser(url: str) -> None:
    open_url(url)


def youtube_url_for(query: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"
