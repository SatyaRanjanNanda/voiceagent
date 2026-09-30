"""Colour palette and stylesheet for the Hudu desktop app."""

BG = "#0c0b0a"
BG_RAISE = "#141210"
BG_SUNK = "#090807"
LINE = "#262220"
LINE_SOFT = "#1c1917"
INK = "#f2ede6"
INK_DIM = "#9c948b"
INK_FAINT = "#6b635b"
AMBER = "#e8a33d"
AMBER_DIM = "#7a5620"
GREEN = "#6fbf7a"
RED = "#d4645a"

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {INK};
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
    font-size: 14px;
}}

#Header {{
    background: {BG};
    border-bottom: 1px solid {LINE};
}}
#Mark {{
    background: {AMBER};
    color: #1a1206;
    border-radius: 7px;
    font-size: 17px;
    font-weight: 700;
}}
#AgentName  {{ font-size: 17px; font-weight: 600; }}
#AgentSub, #SectionLabel, #KeyLabel, .Mono {{
    color: {INK_FAINT};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}
#Chip {{
    color: {INK_DIM};
    background: {BG_RAISE};
    border: 1px solid {LINE};
    border-radius: 11px;
    padding: 5px 11px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}
#ChipLive {{
    color: {GREEN};
    background: #14251a;
    border: 1px solid #24462a;
    border-radius: 11px;
    padding: 5px 11px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}}

#Sidebar {{
    background: {BG_SUNK};
    border-left: 1px solid {LINE};
}}
#SideCard {{
    background: {BG_RAISE};
    border: 1px solid {LINE_SOFT};
    border-radius: 10px;
}}
#KeyValue {{ color: {INK_DIM}; font-size: 13px; }}
#KeyValueValue {{ color: {INK_DIM}; font-family: "Cascadia Mono","Consolas",monospace; font-size: 11px; }}

#Transcript {{
    background: {BG};
    border: none;
    font-family: "Segoe UI", system-ui, sans-serif;
}}

#Composer {{
    background: {BG};
    border-top: 1px solid {LINE};
}}
#Hint {{ color: {INK_FAINT}; font-size: 12px; }}
#Status  {{ color: {INK_FAINT}; font-family: "Cascadia Mono","Consolas",monospace; font-size: 12px; }}
#StatusBusy {{ color: {AMBER}; font-family: "Cascadia Mono","Consolas",monospace; font-size: 12px; }}
#StatusError {{ color: {RED}; font-family: "Cascadia Mono","Consolas",monospace; font-size: 12px; }}

#Mic {{
    background: {BG_RAISE};
    border: 1px solid {LINE};
    border-radius: 30px;
}}
#Mic:hover:!disabled {{ border: 2px solid {AMBER}; }}
#Mic:disabled {{ background: {BG_SUNK}; border: 1px solid {LINE_SOFT}; }}
#MicRecording {{
    background: #1c150c;
    border: 2px solid {AMBER};
    border-radius: 30px;
}}
#LevelTrack {{
    background: {LINE_SOFT};
    border: none;
    border-radius: 3px;
}}
#LevelFill {{
    background: {AMBER};
    border: none;
    border-radius: 3px;
}}

#SendBtn, #DeleteBtn, #YesBtn, #ClearBtn {{
    background: {BG_RAISE};
    border: 1px solid {LINE};
    border-radius: 7px;
    padding: 8px 16px;
    color: {INK};
}}
#SendBtn:hover, #DeleteBtn:hover, #YesBtn:hover, #ClearBtn:hover {{ border: 2px solid {AMBER}; }}
#YesBtn {{ background: #16301a; border: 1px solid #2c5c34; color: #a5e0ac; }}
#YesBtn:hover {{ background: #1c3d22; border: 2px solid #3d7a48; }}
#DeleteBtn {{ background: #2e1614; border: 1px solid #5c2c28; color: #eda9a2; }}
#DeleteBtn:hover {{ background: #3b1c19; border: 2px solid #7a3a35; }}
#SendBtn:disabled, #YesBtn:disabled, #DeleteBtn:disabled {{ color: #4d4741; background: {BG_SUNK}; border: 1px solid {LINE_SOFT}; }}

#ActivityList, #DraftList {{
    background: transparent;
    border: none;
    outline: none;
}}
#ActivityList::item, #DraftList::item {{ padding: 0px; }}
#Empty {{ color: {INK_FAINT}; font-family: "Cascadia Mono","Consolas",monospace; font-size: 12px; }}

QSplitter::handle {{ background: {LINE}; width: 1px; }}
QSplitter::handle:hover {{ background: {AMBER_DIM}; }}

QToolTip {{
    background: {BG_RAISE};
    color: {INK};
    border: 1px solid {LINE};
    padding: 5px;
}}
"""
