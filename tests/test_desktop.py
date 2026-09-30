"""Headless checks for the desktop app. No API key, no display needed.

    python -m tests.test_desktop
"""

from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The 5-arg QMouseEvent constructor is deprecated in Qt 6 but is the only one
# that works for a synthetic press/release without a real pointer device.
warnings.filterwarnings("ignore", category=DeprecationWarning)

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  ok    {label}")
    else:
        FAILED.append(f"{label} {detail}".strip())
        print(f"  FAIL  {label} {detail}")


def main() -> int:
    from PySide6.QtWidgets import QAbstractButton, QApplication

    from voiceagent.desktop import theme
    from voiceagent.desktop.app import HuduWindow
    from voiceagent.desktop.widgets import (
        ActivityList,
        DraftBar,
        PauseButton,
        StatusOrb,
    )

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)

    print("window construction")
    window = HuduWindow()
    window.show()
    check("window builds", window is not None)
    check("has minimum size", window.minimumWidth() > 0)
    check("no text input anywhere", not _find_editable(window))

    print("\ntranscript")
    view = window.transcript
    check("starts empty", view._empty is True)
    view.add_turn("you", "hudu open spotify")
    check("empties on first turn", view._empty is False)
    before = view.document().blockCount()
    view.add_turn("hudu", "Opening Spotify.", ["open_app({}) -> ok=True"])
    check("second turn appends", view.document().blockCount() > before)
    view.add_turn("hudu", "<script>alert(1)</script>")
    check("html in a turn is escaped", "alert(1)" in view.toPlainText())
    view.clear_all()
    check("clear_all resets empty flag", view._empty is True)

    print("\nactivity list")
    activity = window.activity
    check("starts with placeholder", activity.item(0).text() == "nothing yet")
    activity.add_trace(["open_app({}) -> ok=True"])
    check("placeholder is replaced", activity.item(0).text() != "nothing yet")
    check("newest entry is on top", activity.item(0).text().startswith("open_app"))
    activity.add_trace(["boom({}) -> ok=False"])
    activity.add_trace(["second({}) -> ok=True"])
    check("newest is still on top", activity.item(0).text().startswith("second"))
    for _ in range(30):
        activity.add_trace([f"tool{_}({{}}) -> ok=True"])
    check("history is capped", activity.count() <= 15, f"got {activity.count()}")
    activity.show_empty()
    check("show_empty restores placeholder", activity.item(0).text() == "nothing yet")

    print("\nwidgets")
    orb = StatusOrb()
    for state in ("listening", "thinking", "speaking", "paused", "error"):
        orb.set_state(state)
    orb.set_level(3.0)
    orb.set_level(-2.0)
    check("status orb survives state and level changes", True)

    bar = DraftBar()
    bar.show_draft("Alice", "hello there", 3)
    bar.set_busy(True)
    bar.set_busy(False)
    bar.hide_draft()
    check("draft bar survives state changes", True)

    pause = PauseButton()
    check("pause starts unpaused", pause.text() == "Pause listening")
    pause.set_paused(True)
    check("pause shows resume when paused", pause.text() == "Resume listening")

    print("\nwidgets standalone")
    solo_activity = ActivityList()
    solo_orb = StatusOrb()
    solo_bar = DraftBar()
    check("ActivityList constructs", solo_activity.item(0).text() == "nothing yet")
    check("StatusOrb constructs", solo_orb is not None)
    check("DraftBar constructs", solo_bar is not None)

    print("\nhands-free behaviour")
    check("window is not paused at startup", window.paused is False)
    check("no follow-up window at startup", window._in_followup() is False)
    window._followup_until = 9e9
    check("follow-up window opens", window._in_followup() is True)
    window._followup_until = 0.0
    check("follow-up window closes", window._in_followup() is False)
    window._toggle_pause()
    check("pause toggles on", window.paused is True)
    check("cannot listen while paused", window._can_listen() is False)
    window._toggle_pause()
    check("pause toggles back off", window.paused is False)
    check("can listen once resumed", window._can_listen() is True)
    check("orb is not a button", not isinstance(window.orb, QAbstractButton))

    window.close()

    print("\n" + "=" * 60)
    print(f"passed {len(PASSED)}   failed {len(FAILED)}")
    for failure in FAILED:
        print(f"  FAILED: {failure}")
    return 1 if FAILED else 0


def _find_editable(widget) -> bool:
    """The app must be voice-only: no editable text field anywhere.

    QTextBrowser is a QTextEdit subclass, so the transcript display trips a
    naive type check. Read-only views are fine; only editable ones are not.
    """
    from PySide6.QtWidgets import QLineEdit, QTextEdit

    for child in widget.findChildren(QTextEdit):
        if not child.isReadOnly():
            return True
    for child in widget.findChildren(QLineEdit):
        if not child.isReadOnly():
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())
