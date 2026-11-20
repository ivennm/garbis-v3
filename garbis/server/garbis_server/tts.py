"""Text -> speech with edge-tts, in memory (v2's voice settings). Playback happens in the app."""
import edge_tts

from . import config


class Voice:
    async def synthesize(self, text: str) -> bytes:
        communicate = edge_tts.Communicate(
            text=text, voice=config.VOICE, rate=config.VOICE_RATE, pitch=config.VOICE_PITCH
        )
        audio = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        return bytes(audio)


def mp3_duration(mp3: bytes) -> float:
    """Clip length in seconds, from edge-tts's constant bitrate. Only used for safety timeouts."""
    return len(mp3) * 8 / config.TTS_BITRATE
