"""
The conversation engine (ported from garbis-v2/conversation.py, ARCHITECTURE.md §6):
decides who is talking, when Garbis speaks, and what happens when you talk while he's talking.

Every reply is ONE asyncio task (a "turn") made of three workers running at the same time:

    Ollama stream --sentences--> edge-tts --clips--> app (RemotePlayer)

Cancelling the turn task stops all three at once (LLM stream closed, TTS dropped,
`stop_audio` sent so the app cuts playback).

When idle, "garbis" near the start or end of a phrase = talking to him: he answers. "garbis" mid-sentence
= mentioned in passing: a quick YES/NO check decides whether he chimes in (funny / a question he can answer).

While Garbis is talking:
  - "stop" / "shut up" / other STOP_PHRASES -> he stops right away and stays quiet.
  - anything else you say                   -> ignored, he keeps going.
  - exception: if you only said "garbis" and he hasn't started talking yet,
    your next phrase is merged into the question ("garbis ... what's 5+5").
"""
import asyncio
import functools
import itertools
import re
import logging
import time
from typing import Callable, Optional

from . import PROTOCOL_VERSION, __version__, commands, config
from .vad import SpeechEvent, SpeechSegmenter

log = logging.getLogger("garbis.conversation")

_DONE = object()


def is_stop(text: str) -> bool:
    t = " ".join(text.lower().replace(",", " ").replace(".", " ").replace("!", " ").split())
    if t in config.STOP_PHRASES:
        return True
    words = t.split()
    if len(words) > 4:
        return False
    return "stop" in words or any(p in t for p in config.STOP_PHRASES if " " in p)


def addressing(text: str) -> Optional[str]:
    """
    "direct": talking TO Garbis ("hey garbis ...", "garbis, what's ...", "... right, garbis?", short phrases).
    "mentioned": his name came up mid-sentence; a quick check decides whether he chimes in.
    None: no wake word.
    """
    words = re.findall(r"[a-z']+", text.lower())
    spots = [i for i, w in enumerate(words) if w.split("'")[0] == config.WAKE_WORD]
    if not spots:
        return None
    if len(words) <= config.ADDRESS_SHORT:
        return "direct"
    if any(i < config.ADDRESS_HEAD or i >= len(words) - config.ADDRESS_TAIL for i in spots):
        return "direct"
    return "mentioned"


def wants_screen(text: str) -> bool:
    """Is this a question about what's on the screen? (SCREEN_PHRASES, matched on word boundaries)"""
    t = " " + " ".join(re.findall(r"[a-z']+", text.lower())) + " "
    return any(f" {p} " in t or f" {p}s " in t for p in config.SCREEN_PHRASES)


class Turn:
    def __init__(self, turn_id: int, text: Optional[str], source: str, fixed: Optional[list[str]] = None):
        self.id = turn_id
        self.text = text
        self.source = source
        self.fixed = fixed            # pre-written lines (commands) -> no LLM call
        self.optional = False         # overheard mention: only speaks if should_chime_in() says yes
        self.vision = False           # a question about the screen: answered by the vision model
        self.spoken: list[str] = []
        self.task: Optional[asyncio.Task] = None
        self.started_at = time.monotonic()
        self.t_heard = self.started_at   # when you stopped talking
        self.t_stt = self.started_at     # when transcription finished
        self.t_first_text = 0.0          # first sentence back from Ollama
        self.t_first_audio = 0.0         # the app started playing the first clip


class Garbis:
    def __init__(self, ui, brain, voice, player, stt, cmds, post: Callable[[dict | bytes], None],
                 on_memory_changed: Optional[Callable[[bool], None]] = None,
                 on_mode_changed: Optional[Callable[[str], None]] = None):
        self.ui = ui
        self.brain = brain
        self.voice = voice
        self.player = player
        self.stt = stt
        self.cmds = cmds
        self.post = post
        self.on_memory_changed = on_memory_changed     # (evicted) -> save + maybe re-prime
        self.on_mode_changed = on_mode_changed         # (mode) -> save state
        self.turn: Optional[Turn] = None
        self.followup_until = 0.0
        self.last_turn_end = 0.0
        self.mic_speaking = False
        self.mic_muted = False
        self.mode_status = "ready"
        self._turn_ids = itertools.count(1)
        self.screenshot: Optional[bytes] = None       # latest JPEG of the main monitor (RAM only)
        self.screenshot_at = 0.0
        self._screen_requests: dict[int, asyncio.Future] = {}
        self._screen_ids = itertools.count(1)
        self.screen_reason = ""                        # why the app last couldn't send one
        self._tasks: set[asyncio.Task] = set()
        self.segmenters = {
            "mic": SpeechSegmenter("mic", config.MIC_END_SILENCE_MS, self._on_event),
            "desktop": SpeechSegmenter("desktop", config.DESKTOP_END_SILENCE_MS, self._on_event),
        }

    # =========================================================
    # Session handler (see session.py)
    # =========================================================
    def welcome(self) -> dict:
        return {"server_version": __version__, "protocol": PROTOCOL_VERSION,
                "mode": self.brain.mode, "mode_status": self.mode_status, "model": self.brain.model}

    def on_audio(self, source: str, samples):
        self.on_samples(source, samples)

    def on_message(self, msg: dict):
        kind = msg.get("type")
        try:
            if kind == "clip_started":
                self.player.on_clip_started(int(msg["turn_id"]), int(msg["seq"]))
            elif kind == "clip_ended":
                self.player.on_clip_ended(int(msg["turn_id"]), int(msg["seq"]), bool(msg.get("interrupted")))
            elif kind == "set_mode":
                self._spawn(self.set_mode(str(msg.get("mode"))))
            elif kind == "mic_muted":
                self.mic_muted = bool(msg.get("muted"))
            elif kind == "screen_unavailable":
                fut = self._screen_requests.pop(int(msg.get("request_id", 0)), None)
                if fut and not fut.done():
                    fut.set_result(None)
                self.screen_reason = str(msg.get("reason", ""))
                log.info("screen unavailable: %s", self.screen_reason or "?")
            else:
                log.debug("ignored message %r", kind)
        except (KeyError, TypeError, ValueError) as e:
            log.warning("bad %s message: %s", kind, e)

    def on_screen(self, request_id: int, jpeg: bytes):
        self.screenshot, self.screenshot_at = jpeg, time.monotonic()
        fut = self._screen_requests.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(jpeg)

    async def get_screenshot(self) -> Optional[bytes]:
        """A fresh shot of the main monitor if the app answers quickly, else the latest recent one."""
        request_id = next(self._screen_ids)
        fut = asyncio.get_running_loop().create_future()
        self._screen_requests[request_id] = fut
        self.post({"type": "capture_screen", "request_id": request_id})
        try:
            fresh = await asyncio.wait_for(fut, config.SCREEN_REQUEST_TIMEOUT_S)
            if fresh:
                return fresh
        except asyncio.TimeoutError:
            pass
        finally:
            self._screen_requests.pop(request_id, None)
        if self.screenshot and time.monotonic() - self.screenshot_at < config.SCREENSHOT_MAX_AGE_S:
            return self.screenshot
        return None

    def on_active_changed(self, conn):
        self._spawn(self._device_changed(conn))

    async def _device_changed(self, conn):
        """Another app took over, or the active one left: drop whatever was in flight."""
        await self._cancel_turn()
        self.player.reset()
        self.screenshot = None                         # a different device = a different screen
        for seg in self.segmenters.values():
            seg.discard()
        self.mic_speaking = False
        self.followup_until = 0.0
        if conn is not None:
            self.ui.set_state("idle", force=True)      # the new app has no state yet
            self._post_mode()

    # =========================================================
    # Audio in
    # =========================================================
    def on_samples(self, source: str, samples):
        seg = self.segmenters[source]
        if source == "mic":
            # while Garbis talks, react to "stop" faster
            seg.end_silence_ms = (config.STOP_END_SILENCE_MS if self.turn
                                  else config.MIC_END_SILENCE_MS)
        if source == "desktop" and self._desktop_muted():
            seg.discard()            # that's Garbis's own voice coming back through loopback
            return
        seg.feed(samples)

    async def watchdog(self):
        """Finishes a phrase when the app stops sending frames (muted mic, gated desktop audio)."""
        while True:
            now = time.monotonic()
            for seg in self.segmenters.values():
                seg.tick(now)
            await asyncio.sleep(0.1)

    def _desktop_muted(self) -> bool:
        return (
            self.turn is not None
            or self.player.active
            or time.monotonic() - max(self.last_turn_end, self.player.last_audio_end) < config.DESKTOP_TAIL_S
        )

    def _on_event(self, ev: SpeechEvent):
        if ev.source != "mic":
            if ev.kind == "utterance":
                self._spawn(self._on_utterance(ev, time.monotonic()))
            return
        if ev.kind == "start":
            self.mic_speaking = True
            if self.turn is None:
                self.ui.set_state("listen", "mic")
        elif ev.kind == "noise":
            self.mic_speaking = False
            if self.turn is None:
                self.ui.set_state("idle")
        else:
            self.mic_speaking = False
            self._spawn(self._on_utterance(ev, time.monotonic()))

    # =========================================================
    # Deciding what to do with a finished phrase
    # =========================================================
    def _heard(self, source: str, text: str, action: str):
        log.info("[%s] heard: %s  -> %s", source, text, action)
        self.post({"type": "heard", "source": source, "text": text, "action": action})

    async def _on_utterance(self, ev: SpeechEvent, t_heard: float):
        if ev.source == "desktop" and self.stt.busy:
            return                                   # mic gets priority on whisper
        text = await self.stt.transcribe(ev.audio)
        t_stt = time.monotonic()

        if ev.source == "desktop" and self._desktop_muted():
            return
        if not text:
            if ev.source == "mic" and self.turn is None and not self.mic_speaking:
                self.ui.set_state("idle")
            return

        kind = commands.match(text)
        if kind and kind.startswith("mode_") and ev.source != "mic":
            kind = None                              # guests can't switch modes
        address = addressing(text)

        if ev.source == "mic":
            turn = self.turn
            if turn is not None:
                # ---- Garbis is busy (thinking or talking) ----
                if config.INTERRUPTIONS_ENABLED and is_stop(text):
                    self._heard("mic", text, "stop")
                    await self._cancel_turn()
                    self.followup_until = time.monotonic() + config.FOLLOWUP_SECONDS
                    self.ui.set_state("idle")
                    return
                if (turn.source == "mic" and turn.fixed is None and not turn.spoken
                        and turn.text and len(turn.text.split()) <= 3):
                    # "garbis" ... "what's 5+5" -> one question
                    self._heard("mic", text, "merged")
                    merged = f"{turn.text} {text}"
                    await self._cancel_turn()
                    self._start_turn(merged, "mic", turn.t_heard, t_stt)
                    return
                if kind:
                    self._heard("mic", text, "command")
                    self._spawn(self._run_command(kind, text))
                    return
                self._heard("mic", text, "ignored")
                return

            # ---- Garbis is idle ----
            if kind:
                self._heard("mic", text, "command")
                self._spawn(self._run_command(kind, text))
            elif address == "direct":
                look = wants_screen(text)
                self._heard("mic", text, "look" if look else "reply")
                self._start_turn(text, "mic", t_heard, t_stt, vision=look)
            elif address == "mentioned":
                self._heard("mic", text, "mentioned")
                self._start_turn(text, "mic", t_heard, t_stt, optional=True)
            elif time.monotonic() < self.followup_until:
                look = wants_screen(text)
                self._heard("mic", text, "look" if look else "followup")
                self._start_turn(text, "mic", t_heard, t_stt, vision=look)
            else:
                self._heard("mic", text, "ignored")
                if not self.mic_speaking:
                    self.ui.set_state("idle")
            return

        # desktop: guests always need the wake word, and never cut Garbis off
        if self.turn is not None:
            self._heard("desktop", text, "ignored")
            return
        if kind:
            self._heard("desktop", text, "command")
            self._spawn(self._run_command(kind, text))
        elif address == "direct":
            self._heard("desktop", text, "reply")
            self._start_turn(text, "desktop", t_heard, t_stt)
        elif address == "mentioned":
            self._heard("desktop", text, "mentioned")
            self._start_turn(text, "desktop", t_heard, t_stt, optional=True)
        else:
            self._heard("desktop", text, "ignored")

    async def _run_command(self, kind: str, text: str):
        if kind.startswith("mode_"):
            await self.set_mode(kind.removeprefix("mode_"))
        else:
            await self.cmds.run(kind, text, self.say)

    # =========================================================
    # Modes (ARCHITECTURE.md §8)
    # =========================================================
    def _post_mode(self):
        self.post({"type": "mode", "mode": self.brain.mode, "status": self.mode_status, "model": self.brain.model})

    async def set_mode(self, mode: str):
        if mode not in config.MODES or self.mode_status == "loading":
            return
        if mode == self.brain.mode:
            self._post_mode()
            return
        old = self.brain.mode
        self.mode_status = "loading"
        self.brain.mode = mode                   # so the badge shows the target model while loading
        self._post_mode()
        log.info("switching mode %s -> %s", old, mode)
        try:
            await asyncio.gather(self.say([config.SWITCHING_LINE]), self.brain.switch_mode(mode))
        except Exception as e:
            log.warning("mode switch to %s failed: %s", mode, e)
            self.brain.mode = old
            self.post({"type": "error", "code": "brain_down", "message": f"couldn't load {mode} mode: {e}"})
        finally:
            self.mode_status = "ready"
            self._post_mode()
            if self.on_mode_changed:
                self.on_mode_changed(self.brain.mode)

    # =========================================================
    # Turns
    # =========================================================
    def _start_turn(self, text: Optional[str], source: str, t_heard: float = 0.0,
                    t_stt: float = 0.0, fixed: Optional[list[str]] = None, optional: bool = False,
                    vision: bool = False) -> Turn:
        prev = self.turn
        if prev and prev.task and not prev.task.done():
            prev.task.cancel()                    # two phrases raced -- newest wins
        turn = Turn(next(self._turn_ids), text, source, fixed)
        turn.optional = optional
        turn.vision = vision
        if t_heard:
            turn.t_heard, turn.t_stt = t_heard, t_stt
        self.turn = turn
        turn.task = asyncio.create_task(self._run_turn(turn, prev.task if prev else None))
        return turn

    async def _cancel_turn(self):
        turn = self.turn
        if turn and turn.task and not turn.task.done():
            turn.task.cancel()
            await asyncio.wait([turn.task])

    async def say(self, lines: list[str]):
        """Speak fixed lines (used by commands). Waits until done or interrupted."""
        await self._cancel_turn()
        turn = self._start_turn(None, "mic", fixed=lines)
        await asyncio.wait([turn.task])

    async def _run_turn(self, turn: Turn, prev_task: Optional[asyncio.Task] = None):
        if prev_task and not prev_task.done():
            await asyncio.wait([prev_task])       # never two turns playing at once
        if turn.optional and not await self._chime_in(turn):
            return
        self.ui.set_state("think")
        sentences: asyncio.Queue = asyncio.Queue()
        clips: asyncio.Queue = asyncio.Queue(maxsize=2)    # synthesize up to 2 sentences ahead

        async def think():
            if turn.fixed is not None:
                for line in turn.fixed:
                    await sentences.put(line)
            elif turn.vision:
                await sentences.put(config.LOOK_LINE)          # plays while the vision model loads
                shot = await self.get_screenshot()
                if shot is None:
                    await sentences.put(self._cant_see_line())
                else:
                    async for s in self.brain.stream_sentences(turn.text, turn.source, image=shot):
                        if not turn.t_first_text:
                            turn.t_first_text = time.monotonic()
                        await sentences.put(s)
            else:
                async for s in self.brain.stream_sentences(turn.text, turn.source):
                    if not turn.t_first_text:
                        turn.t_first_text = time.monotonic()
                    await sentences.put(s)
            await sentences.put(_DONE)

        async def synthesize():
            while (s := await sentences.get()) is not _DONE:
                try:
                    audio = await self.voice.synthesize(s)
                except Exception as e:
                    log.warning("TTS error: %s", e)
                    continue
                if audio:
                    await clips.put((s, audio))
            await clips.put(_DONE)

        async def speak():
            seq = 0
            while (item := await clips.get()) is not _DONE:
                sentence, audio = item
                # counted as "said" once it starts playing, so an interrupted
                # sentence still goes into memory as what you heard
                self.player.enqueue(turn.id, seq, sentence, audio,
                                    on_start=functools.partial(self._on_audio_start, turn, sentence))
                seq += 1
            if seq:
                await self.player.finish(turn.id)

        interrupted = False
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(think())
                tg.create_task(synthesize())
                tg.create_task(speak())
        except asyncio.CancelledError:
            interrupted = True
            self.player.stop(turn.id)
            log.info("Garbis: (interrupted)")
            raise
        except Exception as e:
            log.warning("turn error: %r", e)
            self.player.stop(turn.id)
            if not turn.spoken:
                await self._speak_error()
        finally:
            if turn.fixed is None and turn.text:
                said = " ".join(turn.spoken)
                if interrupted and said:
                    said += " ... [you got interrupted here]"
                if said:
                    evicted = self.brain.remember(turn.text, turn.source, said)
                    if self.on_memory_changed:
                        self.on_memory_changed(evicted)
            if turn.vision:
                self._spawn(self._restore_after_look())
            if self.turn is turn:
                self.turn = None
                self.last_turn_end = time.monotonic()
                if turn.spoken:                   # no follow-up window if he never said anything
                    self.followup_until = self.last_turn_end + config.FOLLOWUP_SECONDS
                self.ui.set_state("idle")

    def _cant_see_line(self) -> str:
        reason = self.screen_reason.lower()
        if "off" in reason or not reason:
            return config.CANT_SEE_LINE
        if "not allowed" in reason or "permission" in reason or "recording" in reason:
            return config.NO_PERMISSION_LINE
        return config.CANT_CAPTURE_LINE

    async def _restore_after_look(self):
        """Reload the mode's model once Garbis is idle, so the next normal answer is quick again."""
        await asyncio.sleep(0.3)
        while self.turn is not None or self.mode_status == "loading":
            if self.turn is not None and self.turn.vision:
                return                                   # another look is running; it restores afterwards
            await asyncio.sleep(0.3)
        try:
            await self.brain.restore()
        except Exception as e:
            log.warning("couldn't reload %s after looking: %s", self.brain.model, e)

    async def _chime_in(self, turn: Turn) -> bool:
        """Overheard "garbis" mid-sentence: ask the brain whether to speak up. On no, end the turn silently
        (no thinking face, no memory, no follow-up window)."""
        try:
            chime = await self.brain.should_chime_in(turn.text, turn.source)
        except asyncio.CancelledError:
            if self.turn is turn:
                self.turn = None
            raise
        except Exception as e:
            log.warning("chime-in check failed (%s); staying quiet", e)
            chime = False
        log.info("Garbis: %s", "(chiming in)" if chime else "(stayed quiet)")
        if not chime and self.turn is turn:
            self.turn = None
            if not self.mic_speaking:
                self.ui.set_state("idle")
        return chime

    def _on_audio_start(self, turn: Turn, sentence: str):
        if not turn.spoken:
            turn.t_first_audio = time.monotonic()
            self.ui.set_state("speak", turn.source)
            if turn.fixed is None and turn.t_first_text:
                heard = turn.t_stt - turn.t_heard
                first_text = turn.t_first_text - turn.t_stt
                first_audio = turn.t_first_audio - turn.t_first_text
                total = turn.t_first_audio - turn.t_heard
                self.post({"type": "timing", "turn_id": turn.id, "heard_s": round(heard, 3),
                           "first_text_s": round(first_text, 3), "first_audio_s": round(first_audio, 3),
                           "total_s": round(total, 3)})
                if config.SHOW_TIMINGS:
                    log.info("[timing] you stopped talking -> heard: %.2fs | server first words: %.2fs | "
                             "voice: %.2fs | total: %.2fs (+%.2fs waiting to be sure you finished)",
                             heard, first_text, first_audio, total, config.MIC_END_SILENCE_MS / 1000)
        turn.spoken.append(sentence)
        log.info("Garbis: %s", sentence)

    async def _speak_error(self):
        try:
            audio = await self.voice.synthesize("My brain server isn't answering, beep boop.")
            turn_id = next(self._turn_ids)
            self.player.enqueue(turn_id, 0, "My brain server isn't answering, beep boop.", audio)
            await self.player.finish(turn_id)
        except Exception:
            pass

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(_log_task_error)
        return task


def _log_task_error(task: asyncio.Task):
    if not task.cancelled() and task.exception():
        log.error("task error: %r", task.exception())
