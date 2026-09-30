"""Reusable widgets for the Hudu desktop app."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import theme
from ..config import CONFIG


def mono(size: int = 11) -> QFont:
    font = QFont("Cascadia Mono")
    if font.family() not in ("Cascadia Mono", "Consolas"):
        font = QFont("Consolas")
    font.setPointSize(size)
    return font


def label(text: str = "", obj: str = "", size: int = 12, color: str | None = None) -> QLabel:
    widget = QLabel(text)
    if obj:
        widget.setObjectName(obj)
    font = widget.font()
    font.setPointSize(size)
    widget.setFont(font)
    if color:
        widget.setStyleSheet(f"color: {color};")
    return widget


class StatusOrb(QWidget):
    """A non-interactive indicator of what Hudu is doing right now.

    Deliberately not a button: the app is hands-free, so the user never has to
    press anything to be heard.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(60, 60)
        self._state = "listening"
        self._pulse = 0.0

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.update()

    def set_level(self, level: float) -> None:
        self._pulse = max(0.0, min(1.0, level))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        colours = {
            "listening": theme.GREEN,
            "thinking": theme.AMBER,
            "speaking": theme.AMBER,
            "paused": theme.INK_FAINT,
            "error": theme.RED,
        }
        colour = QColor(colours.get(self._state, theme.INK_FAINT))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        size = self.height() - 8
        left = (self.width() - size) / 2
        top = (self.height() - size) / 2

        if self._state == "listening":
            glow = QColor(colour)
            glow.setAlpha(int(40 + self._pulse * 90))
            painter.setBrush(glow)
            painter.drawEllipse(int(left) - 2, int(top) - 2, size + 4, size + 4)

        painter.setBrush(colour)
        painter.drawEllipse(int(left), int(top), size, size)

        # A thin ring outside the orb reads as a microphone without being one.
        pen = QPen(QColor(theme.LINE))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(0, 0, self.width() - 1, self.height() - 1)


class PauseButton(QPushButton):
    """Toggles the microphone. The only control the user actually needs."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ClearBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)
        self.set_paused(False)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.setText("Resume listening" if paused else "Pause listening")


class LevelMeter(QWidget):
    """Thin bar that grows with the live microphone level."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._level = 0.0

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))
        self.update()

    def reset(self) -> None:
        self._level = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        radius = self.height() / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.LINE_SOFT))
        painter.drawRoundedRect(0, 0, self.width(), self.height(), radius, radius)
        if self._level > 0.001:
            width = max(self.height(), self.width() * self._level)
            painter.setBrush(QColor(theme.AMBER))
            painter.drawRoundedRect(0, 0, width, self.height(), radius, radius)


class TranscriptView(QTextBrowser):
    """Renders the conversation as styled HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Transcript")
        self.setOpenExternalLinks(True)
        self.setFrameShape(QTextBrowser.NoFrame)
        self.show_empty()

    def show_empty(self) -> None:
        """A centred placeholder so the window never opens on a blank void."""
        self.clear()
        self._empty = True
        wake = CONFIG.wake_word or "hudu"
        self.setHtml(
            f'<div style="margin:130px 60px 0 60px; text-align:center;">'
            f'<div style="color:{theme.INK_DIM}; font-size:19px; margin-bottom:12px;">'
            f"Say &ldquo;{html.escape(wake)}&rdquo; and ask Hudu anything.</div>"
            f'<div style="color:{theme.INK_FAINT}; font-family:Consolas,monospace; '
            'font-size:12px; line-height:1.9;">'
            "answers out loud &middot; opens your apps<br>"
            "searches the web &middot; plays YouTube &middot; types WhatsApp drafts</div></div>"
        )

    def clear_all(self) -> None:
        self.show_empty()

    def add_turn(self, role: str, text: str, tools: list[str] | None = None) -> None:
        if self._empty:
            self.clear()
            self._empty = False


        who = "YOU" if role == "you" else "HUDU"
        colour = theme.INK_FAINT
        body_bg = theme.BG_SUNK if role == "you" else theme.BG_RAISE
        border = theme.LINE_SOFT if role == "you" else "#33291d"

        chips = ""
        for item in tools or []:
            label_text = html.escape(item.split(" -> ")[0])
            chips += (
                f'<div style="display:inline-block;margin:4px 5px 0 0;padding:3px 7px;'
                f"background:#1c150c;border:1px solid {theme.AMBER_DIM};border-radius:5px;"
                f'color:{theme.AMBER};font-family:Consolas,monospace;font-size:11px;">'
                f"{label_text}</div>"
            )

        block = (
            f'<div style="margin:0 0 18px 0;">'
            f'<div style="color:{colour};font-family:Consolas,monospace;font-size:10px;'
            f'letter-spacing:1.4px;margin-bottom:6px;">{who}</div>'
            f'<div style="background:{body_bg};border:1px solid {border};border-radius:9px;'
            f'padding:11px 14px;color:{theme.INK};font-size:14px;">'
            f"{html.escape(text)}</div>{chips}</div>"
        )

        self.append(block)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


class ActivityList(QListWidget):
    """Most-recent-first list of the tools Hudu ran."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ActivityList")
        self.setFrameShape(QListWidget.NoFrame)
        self.setMaximumHeight(210)
        self.show_empty()

    def show_empty(self) -> None:
        self.clear()
        item = QListWidgetItem("nothing yet")
        item.setForeground(QColor(theme.INK_FAINT))
        item.setFont(mono())
        self.addItem(item)

    def add_trace(self, trace: list[str]) -> None:
        if self.count() == 1 and self.item(0).text() == "nothing yet":
            self.clear()
        for line in trace:
            failed = "ok=False" in line
            name = line.split("(")[0]
            rest = line[line.find("(") + 1 :] if "(" in line else ""
            item = QListWidgetItem(f"{name}  {rest}")
            item.setForeground(QColor(theme.RED if failed else theme.AMBER))
            item.setFont(mono())
            item.setToolTip(line)
            self.insertItem(0, item)
        while self.count() > 14:
            self.takeItem(self.count() - 1)


class SideCard(QWidget):
    """A titled panel in the sidebar."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setObjectName("SideCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(13, 12, 13, 13)
        outer.setSpacing(9)
        title_label = label(title.upper(), "SectionLabel")
        title_label.setStyleSheet(
            f"color: {theme.INK_FAINT}; font-family: Consolas, monospace; "
            "font-size: 10px; letter-spacing: 1.4px; font-weight: 600;"
        )
        outer.addWidget(title_label)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        outer.addLayout(self.body)

    def add_key_value(self, key: str, value: str) -> QLabel:
        row = QWidget()
        row.setObjectName("SideCard")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)
        key_label = label(key, "KeyValue")
        key_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        value_label = label(value, "KeyValueValue")
        value_label.setWordWrap(True)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        row_layout.addWidget(key_label)
        row_layout.addStretch(1)
        row_layout.addWidget(value_label)
        self.body.addWidget(row)
        return value_label


class DraftBar(QWidget):
    """The unsent WhatsApp message, with Send and Delete."""

    send_requested = Signal()
    delete_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SideCard")
        self.setVisible(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 11, 11, 11)
        layout.setSpacing(11)

        text_column = QVBoxLayout()
        text_column.setSpacing(3)
        caption = label("UNSENT DRAFT", "SectionLabel")
        caption.setStyleSheet(
            f"color: {theme.AMBER}; font-family: Consolas, monospace; "
            "font-size: 10px; letter-spacing: 1.4px; font-weight: 600;"
        )
        self.message = label("", size=13)
        self.message.setWordWrap(True)
        self.target = label("", obj="KeyLabel")
        text_column.addWidget(caption)
        text_column.addWidget(self.message)
        text_column.addWidget(self.target)
        layout.addLayout(text_column, 1)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("DeleteBtn")
        self.delete_button.clicked.connect(self.delete_requested.emit)
        self.send_button = QPushButton("Send it")
        self.send_button.setObjectName("YesBtn")
        self.send_button.clicked.connect(self.send_requested.emit)
        layout.addWidget(self.delete_button)
        layout.addWidget(self.send_button)

    def show_draft(self, contact: str, message: str, age_seconds: int) -> None:
        self.message.setText(message)
        self.target.setText(f"to {contact} · waiting {age_seconds}s")
        self.setVisible(True)

    def hide_draft(self) -> None:
        self.setVisible(False)

    def set_busy(self, busy: bool) -> None:
        self.send_button.setEnabled(not busy)
        self.delete_button.setEnabled(not busy)
