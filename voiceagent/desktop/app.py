"""Hudu's desktop window: hands-free. It listens, you just talk."""

from __future__ import annotations

import sys
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from voiceagent import audio, llm, stt, tts
from voiceagent.config import CONFIG
from voiceagent.tools import whatsapp as whatsapp_tools

from . import theme
from .widgets import (
    ActivityList,
    DraftBar,
    PauseButton,
    SideCard,
    StatusOrb,
    TranscriptView,
    label,
)
from .workers import ConfirmTask, RecorderTask, TurnTask, pool

# How long after Hudu speaks it keeps answering without another wake word.
# This is what makes "yes" / "no" work after a WhatsApp draft.
FOLLOWUP_SECONDS = 30
# Pause after Hudu finishes talking, so its own voice is not picked up.
POST_SPEECH_DELAY_MS = 450
# Small gap after a turn so trailing room noise is not treated as speech.
IDLE_GAP_MS = 260

HINTS = (
    f"Say “{CONFIG.wake_word or 'hudu'}” to wake it",
    "What's the tallest mountain?",
    "Open Spotify",
    "Search for news about the Mars rover",
    "Play lofi hip hop on YouTube",
    "Text Alice saying I'm running late",
)


def _voice_name() -> str:
    voices = tts.list_voices()
    if not voices:
        return "none"
    chosen = voices[min(CONFIG.tts_voice_index, len(voices) - 1)]
    if "|" in chosen:
        return chosen.split("|")[1].split("[")[0].strip()
    return chosen


class HuduWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.agent: llm.Agent | None = None
        self.recorder: RecorderTask | None = None
        self.busy = False
        self.paused = False
        self._stop_event = threading.Event()
        self._followup_until = 0.0
        self._pending_resume = False

        self.setWindowTitle(f"{CONFIG.name} — voice assistant")
        self.setMinimumSize(960, 640)
        self.resize(1200, 780)

        self._build_ui()
        self._wire()

    # --- layout -----------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_main(), 1)
        body.addWidget(self._build_sidebar())
        outer.addLayout(body, 1)
        self.setCentralWidget(root)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("Header")
        header.setFixedHeight(66)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(13)

        mark = label(CONFIG.name[:1].upper(), "Mark")
        mark.setFixedSize(32, 32)
        mark.setAlignment(Qt.AlignCenter)
        layout.addWidget(mark)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.addWidget(label(CONFIG.name, "AgentName", size=16))
        self.subtitle = label(f"{CONFIG.model}  ·  {CONFIG.stt_backend} stt", "AgentSub")
        titles.addWidget(self.subtitle)
        layout.addLayout(titles)
        layout.addStretch(1)

        self.chip = label("starting", "Chip")
        layout.addWidget(self.chip)
        return header

    def _build_main(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.transcript = TranscriptView()
        layout.addWidget(self.transcript, 1)
        layout.addWidget(self._build_composer())
        return panel

    def _build_composer(self) -> QWidget:
        composer = QWidget()
        composer.setObjectName("Composer")
        layout = QVBoxLayout(composer)
        layout.setContentsMargins(20, 14, 20, 18)
        layout.setSpacing(11)

        self.draft_bar = DraftBar()
        layout.addWidget(self.draft_bar)

        row = QHBoxLayout()
        row.setSpacing(14)
        self.orb = StatusOrb()
        row.addWidget(self.orb)
        self.status_label = label("", "Status")
        row.addWidget(self.status_label, 1)
        self.pause_button = PauseButton()
        row.addWidget(self.pause_button)
        layout.addLayout(row)
        return composer

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(318)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(14)

        engine = SideCard("Engine")
        engine.add_key_value("Voice", _voice_name())
        engine.add_key_value("Wake word", CONFIG.wake_word or "not required")
        engine.add_key_value("Speech to text", CONFIG.stt_backend)
        layout.addWidget(engine)

        activity_card = SideCard("Activity")
        self.activity = ActivityList()
        activity_card.body.addWidget(self.activity)
        layout.addWidget(activity_card)

        hints = SideCard("Try saying")
        for phrase in HINTS:
            row = QLabel(f"“{phrase}”")
            row.setWordWrap(True)
            row.setStyleSheet(f"color: {theme.INK_DIM}; font-size: 12.5px;")
            hints.body.addWidget(row)
        layout.addWidget(hints)

        self.clear_button = QPushButton("Clear chat")
        self.clear_button.setObjectName("ClearBtn")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        layout.addWidget(self.clear_button)
        layout.addStretch(1)
        return sidebar

    # --- wiring -----------------------------------------------------------

    def _wire(self) -> None:
        self.pause_button.clicked.connect(self._toggle_pause)
        self.draft_bar.send_requested.connect(lambda: self._confirm_draft(True))
        self.draft_bar.delete_requested.connect(lambda: self._confirm_draft(False))
        self.clear_button.clicked.connect(self._clear_chat)

        QShortcut(QKeySequence("Ctrl+R"), self, activated=self._clear_chat)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self._toggle_pause)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)

    # --- small helpers ----------------------------------------------------

    def _status(self, text: str, kind: str = "") -> None:
        self.status_label.setText(text)
        self.status_label.setObjectName(
            {"error": "StatusError", "busy": "StatusBusy"}.get(kind, "Status")
        )
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _chip(self, text: str, live: bool = False) -> None:
        self.chip.setText(text)
        self.chip.setObjectName("ChipLive" if live else "Chip")
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)

    def _state(self, state: str, message: str, kind: str = "") -> None:
        self.orb.set_state(state)
        self._status(message, kind)
        self._chip(message, live=state in {"listening", "thinking", "speaking"})

    def _in_followup(self) -> bool:
        return time.time() < self._followup_until

    def _can_listen(self) -> bool:
        return not self.paused and not self.busy

    # --- the hands-free loop ----------------------------------------------

    def begin(self) -> None:
        """Called once the agent is ready. Starts listening for good."""
        if not audio.list_input_devices():
            self._state(
                "error",
                "No microphone found. Check Windows privacy settings.",
                "error",
            )
            return
        if not CONFIG.tts_enabled:
            self._status("Spoken replies are off. See TTS_ENABLED in .env.", "error")
        QTimer.singleShot(300, self._listen)

    def _listen(self) -> None:
        """Open the mic and wait for the user to say something."""
        if not self._can_listen() or self.agent is None:
            return

        self._stop_event = threading.Event()
        self.recorder = RecorderTask(self._stop_event)
        self.recorder.signals.level.connect(self.orb.set_level)
        self.recorder.signals.finished.connect(self._on_heard)
        pool().start(self.recorder)

        wake = CONFIG.wake_word or "hudu"
        if self._in_followup():
            self._state("listening", "listening — go ahead…", "busy")
        else:
            self._state("listening", f"listening — say “{wake}” to ask something", "busy")

    def _stop_mic(self) -> None:
        self._stop_event.set()
        self.orb.set_level(0.0)

    def _on_heard(self, payload: bytes) -> None:
        """The mic closed for a turn. Decide whether it was addressed to Hudu."""
        if self.paused:
            return

        if self.recorder and self.recorder.error:
            self._state("error", self.recorder.error, "error")
            QTimer.singleShot(2500, self._listen)
            return

        heard = payload.decode("utf-8", "replace") if payload else ""
        if not heard or stt.is_silence(heard):
            # Room noise. Go straight back to listening, saying nothing.
            QTimer.singleShot(IDLE_GAP_MS, self._listen)
            return

        request, heard_wake = stt.strip_wake_word(heard)
        self.transcript.add_turn("you", heard)

        if not (heard_wake or self._in_followup() or not CONFIG.wake_word_required):
            # Not addressed to us. Show it, but do not answer.
            QTimer.singleShot(IDLE_GAP_MS, self._listen)
            return

        if stt.is_silence(request):
            QTimer.singleShot(IDLE_GAP_MS, self._listen)
            return

        self._run_turn(request)

    def _run_turn(self, request: str) -> None:
        if self.agent is None:
            QMessageBox.critical(
                self, "Not ready", "The agent failed to start. See the console for details."
            )
            return
        self.busy = True
        self.draft_bar.set_busy(True)
        self._state("thinking", f"{CONFIG.name} is thinking…", "busy")

        task = TurnTask(self.agent, request, speak=CONFIG.tts_enabled)
        task.signals.trace.connect(self.activity.add_trace)
        task.signals.finished.connect(self._on_reply)
        task.signals.failed.connect(self._on_failed)
        pool().start(task)

    def _on_reply(self, reply: str) -> None:
        self.transcript.add_turn("hudu", reply)
        self.busy = False
        self.draft_bar.set_busy(False)
        # Open the follow-up window so "yes" and "no" work without a wake word.
        self._followup_until = time.time() + FOLLOWUP_SECONDS
        self._refresh_whatsapp()
        self._state("speaking", "speaking…", "busy")
        QTimer.singleShot(POST_SPEECH_DELAY_MS, self._listen)

    def _on_failed(self, message: str) -> None:
        self.busy = False
        self.draft_bar.set_busy(False)
        self._refresh_whatsapp()
        self._state("error", message, "error")
        QTimer.singleShot(3000, self._listen)

    # --- pause / resume ---------------------------------------------------

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_button.set_paused(self.paused)
        if self.paused:
            self._stop_mic()
            self.orb.set_level(0.0)
            self._state("paused", "paused — the microphone is off", "")
        else:
            self._state("listening", "listening…", "busy")
            QTimer.singleShot(300, self._listen)

    # --- whatsapp ---------------------------------------------------------

    def _confirm_draft(self, send: bool) -> None:
        if whatsapp_tools.current_draft() is None:
            self._status("There is nothing waiting to be sent.", "error")
            self._refresh_whatsapp()
            return
        self._stop_mic()
        self.busy = True
        self.draft_bar.set_busy(True)
        self._state("thinking", "sending…" if send else "clearing the draft…", "busy")

        task = ConfirmTask(send=send)
        task.signals.trace.connect(self.activity.add_trace)
        task.signals.finished.connect(self._on_reply)
        task.signals.failed.connect(self._on_failed)
        pool().start(task)

    def _refresh_whatsapp(self) -> None:
        draft = whatsapp_tools.current_draft()
        if draft is None:
            self.draft_bar.hide_draft()
        else:
            self.draft_bar.show_draft(
                draft.contact or "current chat",
                draft.message,
                int(time.time() - draft.typed_at),
            )

    # --- misc -------------------------------------------------------------

    def _clear_chat(self) -> None:
        self.transcript.clear_all()
        self.activity.show_empty()
        if self.agent:
            self.agent.reset()
        self._followup_until = 0.0
        self._status("Chat cleared. Nothing was removed from WhatsApp.", "")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_mic()
        tts.stop()
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    CONFIG.require_api_key()

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(CONFIG.name)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)

    window = HuduWindow()
    window.show()

    try:
        window.agent = llm.Agent()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, "Could not start", f"Failed to create the agent:\n\n{exc}")
        return 1

    window.begin()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
