"""The v2 turn rules, now driven through RemotePlayer / RemoteUI (ARCHITECTURE.md §6)."""
import asyncio
import time

import pytest

from garbis_server import config
from garbis_server.vad import SpeechEvent

from fakes import FakeApp, FakeBrain, make_garbis


async def hear(g, text, source="mic"):
    await g._on_utterance(SpeechEvent("utterance", source, audio=text), time.monotonic())


async def until(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.005)


async def idle(g):
    await until(lambda: g.turn is None)
    await asyncio.sleep(0.01)


async def test_named_question_streams_reply_and_remembers():
    g, app, brain, voice = make_garbis()
    await hear(g, "hey garbis how are you")
    await idle(g)

    assert app.heard() == [("hey garbis how are you", "reply")]
    assert [s["text"] for s in app.of("say")] == ["Hi there.", "Beep boop."]
    assert [(s["turn_id"], s["seq"]) for s in app.of("say")] == [(1, 0), (1, 1)]
    assert len([p for p in app.posts if isinstance(p, bytes)]) == 2
    assert app.of("turn_end") == [{"type": "turn_end", "turn_id": 1}]
    assert app.states() == ["think", "speak", "idle"]
    assert brain.remembered == [("hey garbis how are you", "mic", "Hi there. Beep boop.")]
    assert len(app.of("timing")) == 1
    assert not g.player.active


async def test_stop_cuts_him_off_and_memory_marks_it():
    brain = FakeBrain(replies=[f"Sentence {i}." for i in range(8)])
    g, app, _, _ = make_garbis(brain, FakeApp(play_time=0.2))
    await hear(g, "garbis tell me a long story")
    await until(lambda: g.turn is not None and g.turn.spoken)

    await hear(g, "stop")
    await idle(g)

    assert ("stop", "stop") in app.heard()
    assert app.of("stop_audio") == [{"type": "stop_audio", "turn_id": 1}]
    text, _, said = brain.remembered[0]
    assert said.startswith("Sentence 0.") and said.endswith("[you got interrupted here]")
    assert app.states()[-1] == "idle"
    assert not g.player.active


async def test_other_speech_while_talking_is_ignored():
    brain = FakeBrain(replies=["One.", "Two.", "Three."])
    g, app, _, _ = make_garbis(brain, FakeApp(play_time=0.1))
    await hear(g, "garbis count to three")
    await until(lambda: g.turn is not None and g.turn.spoken)

    await hear(g, "wow what a nice day")
    await idle(g)

    assert ("wow what a nice day", "ignored") in app.heard()
    assert app.of("stop_audio") == []
    assert brain.remembered[0][2] == "One. Two. Three."


async def test_wake_word_then_question_is_merged():
    brain = FakeBrain(replies=["Ten."])
    brain.gate = asyncio.Event()                     # Ollama hasn't answered yet
    g, app, _, _ = make_garbis(brain)
    await hear(g, "garbis")
    await until(lambda: g.turn is not None)

    await hear(g, "what's five plus five")
    brain.gate.set()
    await idle(g)

    assert app.heard() == [("garbis", "reply"), ("what's five plus five", "merged")]
    assert brain.remembered == [("garbis what's five plus five", "mic", "Ten.")]


async def test_followup_window(monkeypatch):
    monkeypatch.setattr(config, "FOLLOWUP_SECONDS", 0.15)
    g, app, brain, _ = make_garbis()
    await hear(g, "garbis hi")
    await idle(g)

    await hear(g, "and how about you")              # no wake word, inside the window
    await idle(g)
    assert app.heard()[-1] == ("and how about you", "followup")

    await asyncio.sleep(0.2)
    await hear(g, "that was fun guys")               # window over
    assert app.heard()[-1] == ("that was fun guys", "ignored")
    assert len(brain.remembered) == 2


async def test_desktop_needs_the_wake_word():
    g, app, brain, _ = make_garbis()
    await hear(g, "nice video everyone", "desktop")
    assert app.heard() == [("nice video everyone", "ignored")]

    await asyncio.sleep(config.DESKTOP_TAIL_S)
    await hear(g, "garbis say hi to chat", "desktop")
    await idle(g)
    assert app.heard()[-1] == ("garbis say hi to chat", "reply")
    assert brain.remembered[0][1] == "desktop"


async def test_desktop_is_muted_while_garbis_talks():
    g, app, _, _ = make_garbis(FakeBrain(replies=["One.", "Two."]), FakeApp(play_time=0.1))
    await hear(g, "garbis hello")
    await until(lambda: g.turn is not None and g.turn.spoken)

    await hear(g, "garbis interrupt you", "desktop")   # his own voice through loopback
    assert [h for h in app.heard() if h[0] == "garbis interrupt you"] == []
    await idle(g)


async def test_device_change_cancels_the_turn():
    brain = FakeBrain(replies=[f"Sentence {i}." for i in range(8)])
    g, app, _, _ = make_garbis(brain, FakeApp(play_time=0.2))
    await hear(g, "garbis tell me a story")
    await until(lambda: g.turn is not None and g.turn.spoken)

    g.on_active_changed(None)                          # the app disconnected
    await idle(g)

    assert app.of("stop_audio")
    assert not g.player.active
    assert brain.remembered[0][2].endswith("[you got interrupted here]")


async def test_mode_switch_by_voice():
    g, app, brain, voice = make_garbis()
    await hear(g, "garbis think hard")
    await until(lambda: g.mode_status == "ready" and brain.switched)
    await idle(g)

    assert app.heard() == [("garbis think hard", "command")]
    assert brain.switched == ["high"]
    assert [(m["mode"], m["status"]) for m in app.of("mode")] == [("high", "loading"), ("high", "ready")]
    assert config.SWITCHING_LINE in voice.spoken
    assert brain.remembered == []                      # fixed lines aren't memory


async def test_guests_cannot_switch_modes():
    g, app, brain, _ = make_garbis()
    await hear(g, "garbis think hard", "desktop")
    await idle(g)
    assert brain.switched == []
    assert app.heard() == [("garbis think hard", "reply")]   # treated as a normal guest question


async def test_brain_down_says_so():
    brain = FakeBrain()
    brain.fail = True
    g, app, _, voice = make_garbis(brain)
    await hear(g, "garbis hello")
    await idle(g)
    await until(lambda: not g.player.active)
    assert "My brain server isn't answering, beep boop." in voice.spoken
    assert brain.remembered == []


async def test_set_mode_message_from_app():
    g, app, brain, _ = make_garbis()
    g.on_message({"type": "set_mode", "mode": "high"})
    await until(lambda: brain.switched == ["high"] and g.mode_status == "ready")
    g.on_message({"type": "set_mode", "mode": "nonsense"})
    await asyncio.sleep(0.02)
    assert brain.switched == ["high"]


@pytest.mark.parametrize("respond", [False])
async def test_turn_finishes_even_if_app_never_reports(monkeypatch, respond):
    monkeypatch.setattr(config, "CLIP_TIMEOUT_PAD_S", 0.05)
    g, app, brain, _ = make_garbis(app=FakeApp(respond=respond))
    await hear(g, "garbis hello")
    await idle(g)
    assert not g.player.active
    assert brain.remembered == []                      # nothing was confirmed as played
