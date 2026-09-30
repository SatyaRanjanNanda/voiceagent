"""Hudu's brain: a Gemini function-calling loop with a spoken-first persona."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

from google import genai
from google.genai import types

from .config import CONFIG
from .tools import declarations, call
from .tools import whatsapp as whatsapp_tools

MAX_TOOL_ROUNDS = 8
# Gemini regularly returns 503 "high demand" or 429 rate limits. A voice
# assistant should shrug those off rather than dead-end the conversation.
STREAM_ATTEMPTS = 3
RETRY_BASE_DELAY = 1.5
RETRYABLE = {"429", "500", "502", "503", "504", "RESOURCE_EXHAUSTED", "UNAVAILABLE"}

PERSONA = """You are {name}, a voice assistant running on the user's own Windows computer.
Your name is {name}. If asked your name, say "{name}". Never call yourself an AI model, an
assistant, a language model, or an agent. You are {name}.

VOICE STYLE
- You are being listened to, not read. Speak in one or two short sentences.
- No markdown, no bullet lists, no emoji, no code blocks, no URLs spoken aloud.
- No filler like "Certainly!" or "I'd be happy to". Just say the thing.
- Numbers, names, and symbols are fine. Expand the obvious, like "two thousand twenty six".
- When a tool already did the job, confirm it in a few words and stop. Do not narrate steps
  you did not take.

CAPABILITIES
- Answer questions out loud, from your own knowledge, in whatever language the user speaks.
- Launch apps, search Google, and play things on YouTube.
- Type WhatsApp messages for the user.

WHATSAPP PROTOCOL - THIS IS STRICT
- The moment the user asks for a message to be written, call whatsapp_type with the contact
  and the exact words. This NEVER sends anything; it only fills the composer.
- Then you MUST ask out loud whether to send it. Do not call whatsapp_confirm yet.
- A pending draft is flagged in the context below. When it is there, a bare "yes", "yeah",
  "send it", "go ahead" means send=true, and "no", "nah", "delete it", "cancel", "clear it"
  means send=false. Call whatsapp_confirm with that value, then confirm briefly in words.
- If the user changes the wording instead of answering, clear the draft with
  whatsapp_confirm(send=false) before typing the new version.
- If the user says no, confirm that it was cleared. Never claim a message was sent unless
  whatsapp_confirm returned sent=true.

JUDGEMENT
- Prefer acting over explaining. If a tool fits the request, call it.
- If an action is destructive or outward facing and the user did not clearly ask for it, ask
  first in one short sentence.
- If you genuinely do not know something, say so plainly. Do not invent facts."""


class Agent:
    def __init__(self, client: genai.Client | None = None) -> None:
        CONFIG.require_api_key()
        self.client = client or genai.Client(api_key=CONFIG.api_key)
        self._system = PERSONA.format(name=CONFIG.name)
        self._history: list[types.Content] = []
        self._tool_config = types.GenerateContentConfig(
            system_instruction=self._system,
            tools=[types.Tool(function_declarations=declarations())],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            temperature=0.7,
            # Generous, because reasoning tokens come out of this budget too
            # and a low cap can return an empty reply.
            max_output_tokens=4096,
        )
        self.last_tool_trace: list[str] = []

    # --- history ----------------------------------------------------------

    def _live_context(self) -> str:
        """Facts about right now that the model cannot otherwise know."""
        draft = whatsapp_tools.current_draft()
        if draft is None:
            return "NO WhatsApp draft is pending."
        target = draft.contact or "the currently open chat"
        return (
            "A WhatsApp draft is PENDING and UNSENT. "
            f"Target: {target}. Text: {draft.message!r}. "
            "The user's next words are most likely an answer to your send/don't-send "
            "question. Resolve it by calling whatsapp_confirm."
        )

    def _trim(self) -> None:
        limit = CONFIG.history_turns * 2
        if len(self._history) <= limit:
            return
        head = self._history[0]
        self._history = [head] + self._history[-limit:]

    def reset(self) -> None:
        self._history.clear()
        self.last_tool_trace.clear()

    # --- main loop --------------------------------------------------------

    def respond(self, user_text: str) -> Iterator[str]:
        """Yield text chunks of the reply while running any tools it asks for."""
        self.last_tool_trace = []
        context = f"[Live context] {self._live_context()}"
        self._history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=f"{user_text}\n\n{context}")],
            )
        )

        tool_results: list[types.Content] = []

        for _ in range(MAX_TOOL_ROUNDS):
            try:
                text, calls, model_parts = self._one_turn(tool_results)
            except Exception as exc:  # noqa: BLE001
                # Close the turn out, otherwise the next user message would sit
                # next to an unanswered one and confuse the model.
                self._history.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text="(I could not answer that just now.)")],
                    )
                )
                yield f"I ran into a problem reaching Gemini: {exc}"
                return

            if not calls:
                if not text:
                    text = "I did not catch a reply to that."
                self._history.append(types.Content(role="model", parts=model_parts))
                yield text
                return

            # Run every requested tool, then feed the results back for one more turn.
            self._history.append(types.Content(role="model", parts=model_parts))
            parts: list[types.Part] = []
            for call_item in calls:
                name = call_item.name or ""
                args = _parse_args(call_item.args)
                result = call(name, args)
                self.last_tool_trace.append(
                    f"{name}({json.dumps(args, default=str)}) -> ok={result.get('ok')}"
                )
                parts.append(
                    types.Part.from_function_response(name=name, response={"result": _slim(result)})
                )
            tool_results.append(types.Content(role="user", parts=parts))

        yield "That took me more steps than I expected. Let us start that one again."

    def _one_turn(
        self, tool_results: list[types.Content]
    ) -> tuple[str, list[types.FunctionCall], list[types.Part]]:
        """Stream one model turn, splitting the reply text from any tool calls.

        The SDK hands back a generator of partial chunks, so this has to be a
        single pass: collect the text as it arrives, and pick up the function
        calls from whichever chunk carries them. Each model gets a few tries
        before falling through to the next one, because a single Gemini model
        can be throttled while another is fine.
        """
        contents = [*self._history, *tool_results]
        problems: list[str] = []

        for model in CONFIG.model_chain():
            for attempt in range(1, STREAM_ATTEMPTS + 1):
                text_parts: list[str] = []
                calls: list[types.FunctionCall] = []
                model_parts: list[types.Part] = []
                try:
                    for chunk in self.client.models.generate_content_stream(
                        model=model, contents=contents, config=self._tool_config
                    ):
                        for candidate in chunk.candidates or []:
                            for part in candidate.content.parts or []:
                                if part.function_call:
                                    calls.append(part.function_call)
                                    model_parts.append(part)
                                elif part.text:
                                    text_parts.append(part.text)
                                    model_parts.append(part)
                    if text_parts or calls:
                        return "".join(text_parts).strip(), calls, model_parts
                    problems.append(f"{model}: returned an empty reply")
                    break
                except Exception as exc:  # noqa: BLE001
                    problems.append(f"{model}: {str(exc)[:140]}")
                    if not _is_retryable(exc):
                        break  # a bad key or bad config will not fix itself
                    if attempt < STREAM_ATTEMPTS:
                        time.sleep(RETRY_BASE_DELAY * attempt)

        raise AgentError(diagnose(problems))

    # --- text mode --------------------------------------------------------

    def ask_text(self, user_text: str) -> str:
        """One-shot reply with no tools, for the typed console mode."""
        config = types.GenerateContentConfig(
            system_instruction=self._system,
            temperature=0.7,
            max_output_tokens=4096,
        )
        try:
            response = self.client.models.generate_content(
                model=CONFIG.model, contents=user_text, config=config
            )
        except Exception as exc:  # noqa: BLE001
            raise AgentError(f"Gemini request failed: {exc}") from exc
        return (response.text or "").strip()


class AgentError(RuntimeError):
    pass


def _is_retryable(exc: Exception) -> bool:
    """True for transient capacity/rate problems worth trying again."""
    text = str(exc)
    return any(code in text for code in RETRYABLE)


def diagnose(problems: list[str]) -> str:
    """Turn a list of raw API failures into one sentence a human can act on.

    Spoken aloud in a voice assistant, this is the difference between
    "something went wrong" and knowing to go and raise a quota limit.
    """
    blob = " ".join(problems).lower()

    if not problems:
        return "I did not get a reply from Gemini."

    if "api key not valid" in blob or "api_key_invalid" in blob or "401" in blob:
        return (
            "That Google API key was rejected. Check GOOGLE_API_KEY in your .env file."
        )
    if "permission_denied" in blob or "403" in blob:
        return "That key is not allowed to use this model. Check the key's permissions."
    if "quota" in blob or "resource_exhausted" in blob or "429" in blob:
        return (
            "You have hit your Gemini rate limit or run out of free quota. "
            "Wait a minute, or use a different key in .env. "
            "You can check your usage at aistudio.google.com."
        )
    if "no longer available to new users" in blob or "404" in blob:
        return (
            "That model is not available on your key. Set GEMINI_MODEL to "
            "gemini-3.5-flash in your .env file."
        )
    if "503" in blob or "unavailable" in blob or "high demand" in blob:
        return "Gemini is very busy right now. Try again in a moment."
    if "400" in blob:
        return "Gemini rejected that request as malformed."

    first = problems[0].split(":", 1)[-1].strip()
    return f"Gemini could not answer right now. {first[:120]}"


def _parse_args(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"value": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {}


def _slim(result: dict, limit: int = 1200) -> dict:
    """Keep tool payloads small enough to stay cheap and inside the context."""
    trimmed = {}
    for key, value in result.items():
        if isinstance(value, str) and len(value) > limit:
            value = value[:limit] + " ...[truncated]"
        elif isinstance(value, list) and len(value) > 40:
            value = value[:40] + ["...truncated"]
        trimmed[key] = value
    return trimmed


def warm_up() -> None:
    """Tiny call so the first real turn is not slowed by connection setup."""
    client = genai.Client(api_key=CONFIG.api_key)
    started = time.time()
    client.models.generate_content(
        model=CONFIG.model,
        contents="ping",
        config=types.GenerateContentConfig(max_output_tokens=1),
    )
    return time.time() - started
