"""Pure text helpers: speech cleanup, sentence splitting, wake-word fixes, stop phrases, commands."""
import pytest

from garbis_server import commands
from garbis_server.brain import tag
from garbis_server.conversation import is_stop
from garbis_server.speech import SentenceSplitter, speakable
from garbis_server.stt import clean_transcript, fix_garbis


@pytest.mark.parametrize("raw, spoken", [
    # equations the 4B wrote in the high-mode tests (PLAN.md §7)
    ("KDA = (kills + assists) / deaths", "KDA equals kills plus assists divided by deaths"),
    ("(3 + 12) / 7 ≈ 2.14", "3 plus 12 divided by 7 is about 2.14"),
    ("15 / 7 ≈ 2.14 beep.", "15 divided by 7 is about 2.14 beep."),
    ("So 2x + 1 = 1.10", "So 2x plus 1 equals 1.10"),
    ("Ball costs $0.05.", "Ball costs 5 cents."),
    ("The ball is $0.50.", "The ball is 50 cents."),
    ("Together $1.10 total", "Together 1 dollar 10 total"),
    ("It costs $5.", "It costs 5 dollars."),
    ("It costs $1", "It costs 1 dollar"),
    ("about 50% of the time", "about 50 percent of the time"),
    ("3 × 4", "3 times 4"),
    ("10 - 4 = 6", "10 minus 4 equals 6"),
    # emoji, markdown, lists
    ("The capital of Australia is Canberra. Beep boop! 🚀", "The capital of Australia is Canberra. Beep boop!"),
    ("Your KDA is **2.14** 😊", "Your KDA is 2.14"),
    ("1. Assign clear roles.", "Assign clear roles."),
    ("- Stay together", "Stay together"),
    ("Let the ball cost *x*.", "Let the ball cost x."),
    # things that must stay as they are
    ("Pages 2-3 are good.", "Pages 2-3 are good."),
    ("Hello Supreme Master Leader Sama, beep.", "Hello Supreme Master Leader Sama, beep."),
])
def test_speakable(raw, spoken):
    assert speakable(raw) == spoken


def test_splitter_cuts_sentences_and_first_clause():
    s = SentenceSplitter()
    out = []
    # the comma cut only happens while the first sentence's end hasn't streamed in yet
    for token in ["Beep boop, that game is a total banger, ", "Supreme Master Leader Sama. ",
                  "I give it nine out of ten. ", "Beep!"]:
        out += s.push(token)
    out += s.flush()
    assert out == ["Beep boop, that game is a total banger,", "Supreme Master Leader Sama.",
                   "I give it nine out of ten.", "Beep!"]


def test_splitter_drops_symbol_only_chunks():
    s = SentenceSplitter()
    assert s.push("🚀🚀\n") == []
    assert s.flush() == []


@pytest.mark.parametrize("heard, fixed", [
    ("Garbies, what's up?", "garbis, what's up?"),
    ("Hey Garby's, stop.", "hey garbis, stop."),
    ("Jarvis what time is it", "garbis what time is it"),
    ("Garbis, think hard.", "garbis, think hard."),
    ("I like garbage collection", "i like garbis collection"),     # v2 behavior: known trade-off
])
def test_fix_garbis(heard, fixed):
    assert fix_garbis(heard).lower() == fixed


@pytest.mark.parametrize("junk", ["Thank you.", "you", " Bye! ", "Thanks for watching!"])
def test_junk_is_dropped(junk):
    assert clean_transcript(junk) == ""


@pytest.mark.parametrize("text, stop", [
    ("stop", True), ("stop.", True), ("garbis stop", True), ("shut up", True), ("okay, stop!", True),
    ("never mind", True), ("can you stop the music for me please", False), ("what's up", False),
])
def test_is_stop(text, stop):
    assert is_stop(text) is stop


@pytest.mark.parametrize("text, kind", [
    ("garbis clip that", "clip"),
    ("garbis, think hard.", "mode_high"),
    ("garbis high mode", "mode_high"),
    ("garbis chill", "mode_low"),
    ("garbis low mode!", "mode_low"),
    ("garbis how do i chill out", None),          # whole phrase must match
    ("think hard", None),                          # wake word required
])
def test_command_match(text, kind):
    assert commands.match(text) == kind


def test_guest_tag():
    assert tag("garbis hi", "desktop") == "[guest] garbis hi"
    assert tag("garbis hi", "mic") == "garbis hi"
