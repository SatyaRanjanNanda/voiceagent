# Hudu

A local voice assistant for Windows. You talk, Hudu answers out loud, opens your apps,
searches the web, plays things on YouTube, and types WhatsApp messages for you.

Powered by Google's Gemini API. Speech recognition runs through Gemini by default, so one
API key is all you need.

---

## What it does

| Ask Hudu to... | What happens |
| --- | --- |
| "What's the capital of Peru?" | Answers out loud, no tools needed |
| "Open Spotify" | Fuzzy-matches your installed apps and launches it |
| "Search Google for the best pizza in town" | Opens Google results |
| "Play lofi hip hop on YouTube" | Finds the video and plays it |
| "Put on some Daft Punk" | Picks the best audio upload and plays it |
| "Text Alice saying I'll be ten minutes late" | Opens WhatsApp, finds Alice, **types it without sending** |
| "Yes" / "No" | Sends it, or clears the draft |
| "Volume up" / "Mute" / "Lock my PC" | System controls |

---

## Setup

### 1. Get an API key

Go to <https://aistudio.google.com/apikey>, create a key, and copy it.

### 2. Install

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Add your key

```powershell
Copy-Item .env.example .env
notepad .env
```

Paste your key into `GOOGLE_API_KEY`.

### 4. Launch

```powershell
python run.py --gui
```

The window opens and starts listening. That is it — there is no button to press.
Just say **"Hudu"** and ask your question.

---

## How the hands-free loop works

```
listening  ──you say "Hudu, open Spotify"──▶  thinking  ──▶  speaking
     ▲                                                       │
     └────────────── 0.5s after it stops talking ────────────┘
```

- It only answers when you say the wake word, so it ignores background chatter.
- After it replies, it keeps listening for **30 seconds without needing the wake
  word again**. That is what makes "yes" and "no" work for a WhatsApp draft.
- Speech is detected by volume, so there is no button and no hotkey to hold.
- Silence costs nothing: audio is only sent for transcription when you actually
  speak, so a quiet room makes no API calls.

The green orb means it is listening, amber means thinking or speaking, grey means
paused, red means something went wrong.

**Pause listening** (or `Ctrl+P`) is the only control you need. `Ctrl+R` clears the
transcript, `Ctrl+Q` quits.

---

## The WhatsApp safety rule

Hudu never sends a message on its own. The flow is always:

1. You say "Hudu, text Alice saying hello".
2. Hudu opens WhatsApp, opens the chat, and **types the message**.
3. An orange **unsent draft** bar appears with **Send it** and **Delete** buttons.
4. Say **"yes"** (or click Send it) to send. Say **"no"** (or click Delete) to clear it.

The buttons are there as a backup for when the room is too loud for a voice answer.
Nothing is sent until you confirm one way or the other.

If you want to reword the message instead of answering, just say the new version.
Hudu clears the old draft before typing the new one.

The draft is held in memory and expires after 15 minutes, so a forgotten "yes" cannot
fire later.

---

## Command line options

The desktop app is the main way to use Hudu, but the terminal still works for
debugging and for machines with no usable microphone.

| Command | What it does |
| --- | --- |
| `python run.py --gui` | Launch the desktop app. The normal way to use Hudu. |
| `python run.py --text` | Typed conversation in the terminal. Useful for testing. |
| `python run.py` | Terminal voice mode, push to talk with Space. |
| `python run.py --check` | Verify the setup and report anything missing. |
| `python run.py --voices` | List the installed voices. |
| `python run.py --devices` | List the microphones Windows can see. |

---

## Configuration

Everything lives in `.env`.

| Variable | Default | Notes |
| --- | --- | --- |
| `GOOGLE_API_KEY` | — | Required |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Swap for `gemini-2.5-pro` if you want deeper answers |
| `AGENT_NAME` | `Hudu` | The name it answers to |
| `STT_BACKEND` | `gemini` | `gemini` or `cloud` |
| `WAKE_WORD` | `hudu` | Spoken to get its attention |
| `WAKE_WORD_REQUIRED` | `true` | `false` = it answers anything it hears |
| `TTS_ENABLED` | `true` | `false` = only show replies, never speak |
| `TTS_RATE` | `175` | Words per minute |
| `TTS_VOICE_INDEX` | `0` | Run `python run.py --voices` to see the list |
| `MAX_RECORD_SECONDS` | `20` | Cap on a single turn |

### Speech recognition backends

`STT_BACKEND=gemini` sends the microphone audio straight to Gemini. One key, no extra
setup, good accuracy. This is the default.

`STT_BACKEND=cloud` uses Google Cloud Speech-to-Text instead. It is more accurate on
noisy audio, but **it does not accept a plain API key** — it needs a service account:

```powershell
pip install google-cloud-speech
```

Then in `.env`:

```
STT_BACKEND=cloud
GOOGLE_APPLICATION_CREDENTIALS=C:/Users/you/keys/gcp-speech.json
GOOGLE_CLOUD_PROJECT=your-project-id
```

Enable the Cloud Speech-to-Text API in the Google Cloud console first.

---

## Troubleshooting

**Hudu never hears me.** Check Windows privacy: Settings > Privacy > Microphone, and make
sure desktop apps can access it. Run `python run.py --devices` to confirm the mic is
visible.

**Hudu answers things you did not ask it.** Lower the VAD sensitivity by raising the
multiplier in `_noise_floor() * 3.2` in `voiceagent/audio.py`, or turn the wake word
back on with `WAKE_WORD_REQUIRED=true`.

**Hudu answers things nobody said.** It picked up its own voice. Raise
`POST_SPEECH_DELAY_MS` in `voiceagent/desktop/app.py`.

**No sound.** Check `python run.py --voices` and set `TTS_VOICE_INDEX` to a working index.

**"YouTube lookup failed."** Run `pip install -U yt-dlp`. YouTube changes often and older
yt-dlp versions break.

**Wrong app opens.** Hudu deliberately refuses a fuzzy guess below 75% confidence and asks
instead. Add a name to `ALIASES` in `voiceagent/tools/apps.py` if you want an exact match.

**The mouse jumps to a corner.** That is the PyAutoGUI failsafe and it is intentional.
Hudu stops immediately rather than clicking somewhere unintended. Nothing gets sent.

---

## Project layout

```
run.py                       entry point and flags
voiceagent/
  config.py                  .env loading and settings
  audio.py                   mic capture and voice activity detection
  stt.py                     transcription, both backends
  tts.py                     spoken replies via Windows SAPI voices
  llm.py                     the Gemini function-calling loop and Hudu's persona
  console.py                 UTF-8 terminal fix
  tools/
    __init__.py              tool registry and Gemini schemas
    apps.py                  fuzzy app launching
    web.py                   Google search and YouTube via yt-dlp
    whatsapp.py              open, type, confirm, or clear
    system.py                volume, mute, lock, screenshot
  desktop/
    app.py                   the window and the hands-free state machine
    widgets.py               orb, draft bar, transcript, activity list
    workers.py               background recording and agent turns
    theme.py                 colours and stylesheet
tests/
  test_offline.py            69 tests, no API key needed
  test_desktop.py            30 tests, no display needed
```

Run the tests any time:

```powershell
python -m tests.test_offline
python -m tests.test_desktop
```

---

## Safety notes

- Nothing is sent to WhatsApp without an explicit yes, by voice or by button.
- `shutdown_computer` asks first and uses a delay so you can cancel.
- `lock_computer` only runs on an explicit request.
- A WhatsApp draft expires after 15 minutes.
- The mouse-corner failsafe stops all keyboard and mouse control instantly.
- Screen control stays on your machine. The only thing that leaves is your microphone
  audio, your spoken requests, and the Google searches you ask for.
