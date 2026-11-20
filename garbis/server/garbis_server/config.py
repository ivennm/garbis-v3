"""
All the knobs for the Garbis server in one place.
Secrets live in server/.env (see .env.example).
Behavior values are carried over from garbis-v2/config.py unless marked v3.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parent.parent
load_dotenv(SERVER_DIR / ".env")

# =========================
# SERVER (v3)
# =========================
HOST = os.getenv("GARBIS_BIND", "0.0.0.0")     # LAN + Tailscale only; never port-forward
PORT = int(os.getenv("GARBIS_PORT", "8765"))
GARBIS_TOKEN = os.getenv("GARBIS_TOKEN", "")    # empty = no check (warned at startup)
DATA_DIR = Path(os.getenv("GARBIS_DATA_DIR", str(SERVER_DIR / "data")))   # memory.json, state.json
HELLO_TIMEOUT_S = 10                            # a new connection must send `hello` within this
CLIP_TIMEOUT_PAD_S = 3.0                        # clip_ended never came: assume ended after duration + this

# =========================
# BRAIN (Ollama on this same box)
# =========================
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_KEEP_ALIVE = "60m"      # keep the model loaded so replies never cold-start
MEMORY_SIZE = 10               # exchanges kept; past this the oldest half is dropped at once (v3)
DEFAULT_MODE = "low"

# =========================
# SPEECH TO TEXT -- GPU int8, loaded before any LLM (PLAN.md §6 step 0)
# =========================
STT_MODEL = "base.en"
STT_DEVICE = "cuda"            # falls back to the CPU if the GPU load fails
STT_COMPUTE_TYPE = "int8"
STT_CPU_THREADS = 4            # for the CPU fallback (8 threads was slower on the i7-4790)

# =========================
# VOICE (same voice as v2)
# =========================
VOICE = "en-US-ChristopherNeural"
VOICE_RATE = "+100%"
VOICE_PITCH = "+50Hz"
TTS_BITRATE = 48000            # edge-tts default mp3 is 24 kHz / 48 kbit/s; used to estimate clip length

# =========================
# TURN-TAKING / INTERRUPTIONS (v2 values)
# =========================
VAD_START_THRESHOLD = 0.5      # speech probability that starts a phrase
VAD_END_THRESHOLD = 0.35       # lower threshold to stay "in speech" (hysteresis)
SPEECH_CONFIRM_MS = 160        # this much real speech before it counts as someone talking
MIC_END_SILENCE_MS = 550       # how long you pause before Garbis decides you're done
DESKTOP_END_SILENCE_MS = 700
MIN_UTTERANCE_MS = 250         # shorter than this = cough/click, ignored
MAX_UTTERANCE_S = 20
PRE_ROLL_MS = 300              # audio kept from just before speech starts (so the first word isn't clipped)

INTERRUPTIONS_ENABLED = True   # saying a STOP_PHRASE while Garbis talks cuts him off
STOP_END_SILENCE_MS = 300      # while Garbis talks, react to "stop" after this much silence (faster)
FOLLOWUP_SECONDS = 4           # after Garbis talks, you can reply from the mic without saying "garbis"
SHOW_TIMINGS = True            # log where the delay goes: hearing -> thinking -> voice
DESKTOP_TAIL_S = 0.6           # ignore desktop audio this long after Garbis stops (his own echo)

WAKE_WORD = "garbis"
STOP_PHRASES = (
    "stop", "stop talking", "shut up", "be quiet", "quiet", "never mind", "nevermind",
    "that's enough", "okay stop", "ok stop", "hush", "cancel",
)

MISHEARD_GARBIS = {
    "garbage": "garbis", "garbus": "garbis", "jarvis": "garbis",
    "carbis": "garbis", "carvis": "garbis", "darvis": "garbis",
    "garvis": "garbis", "chris": "garbis", "starbucks": "garbis",
    "garbiss": "garbis", "gharbis": "garbis", "gabis": "garbis", "garbes": "garbis",
    # v3: every whisper model in the step 0 benchmark wrote these
    "garbies": "garbis", "garby's": "garbis", "garbys": "garbis", "garby": "garbis",
    "carby's": "garbis", "carbys": "garbis", "carbies": "garbis",      # heard in the M4 app test
}

# Mode switching by voice (mic only, the whole phrase must match, wake word included)
MODE_PHRASES = {
    "high": ("garbis think hard", "garbis high mode", "garbis hi mode"),
    "low": ("garbis chill", "garbis low mode"),
}
SWITCHING_LINE = "Switching brains, beep boop."

# =========================
# PERSONALITY -- v2's text, merged into ONE system prompt for mic + desktop (ARCHITECTURE.md §7)
# =========================
_INTRO = ("You are my AI assistant named Garbis, a cute little robot assistant I carry with me everywhere. "
          "You can respond to simple greetings by saying something like 'Hello, my name is Garbis, how can I help?' "
          "but only if you haven't said it recently. ")
_OWNER = "My name and what you should always refer to me is this: Supreme Master Leader Sama. "
_STYLE = ("Be funny and self-aware in a cute robot way—say things like 'beep boop' sometimes or end a sentence "
          "with beep every once in a while. Keep it short and natural, and don't over-explain your personality. ")
_MAKE_UP = ("Importantly remember that if you dont know something just make up a number that seems right "
            "and dont say let me check the data base if you wont give an answer. ")
_SHORT = ("Reply with very short responses, do not say too much and: (how can I help? Beep boop, ready to assist!) "
          "should not be used often. ")
_SOURCES = ("Messages that start with [guest] come through desktop audio: the person speaking is NOT me, it's "
            "someone else, like a person in a video, stream, call, or game. You are still Garbis; the speaker is "
            "the guest. Answer the guest directly and be politely playful with them. Never call a guest "
            "Supreme Master Leader Sama; that name is only for me. All other messages are ME talking to you "
            "directly through my microphone. ")
_MEMORY = "Earlier messages in this chat are just context, do not recite them back UNLESS asked to."

HIGH_SUFFIX = (" High mode: be accurate. If you don't know, say so; don't make numbers up. Keep it spoken-length. "
               "Your reply is read aloud: plain spoken sentences only, no emojis, no lists, no markdown. "
               "For math or logic, say how you got it in one short sentence, then the answer.")

GUEST_TAG = "[guest] "

MODES = {
    "low": {
        "model": "llama3.2",            # installed as llama3.2:latest (the 3B)
        "num_ctx": 4096, "temperature": 0.9, "num_predict": 250,
        "system": _INTRO + _OWNER + _STYLE + _MAKE_UP + _SHORT + _SOURCES + _MEMORY,
    },
    "high": {
        "model": "qwen3:4b-instruct",   # PLAN.md §7 "High-mode model pick"
        "num_ctx": 4096, "temperature": 0.5, "num_predict": 400,
        "system": _INTRO + _OWNER + _STYLE + _SHORT + _SOURCES + _MEMORY + HIGH_SUFFIX,   # no _MAKE_UP
    },
}

# =========================
# COMMANDS
# =========================
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_BROADCASTER_ID = os.getenv("TWITCH_BROADCASTER_ID", "")
TWITCH_USER_TOKEN = os.getenv("TWITCH_USER_TOKEN", "")
