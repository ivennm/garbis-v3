"""
Voice commands that skip the LLM: Twitch clips (v2) and mode switching (v3).
"""
import asyncio
import logging
import re
from typing import Optional

from . import config

log = logging.getLogger(__name__)


def _phrase(text: str) -> str:
    return " ".join(re.sub(r"[^a-z' ]+", " ", text.lower()).split())


def match(text: str) -> Optional[str]:
    """Returns "clip", "mode_high", "mode_low" or None."""
    if "clip that" in text:
        return "clip"
    phrase = _phrase(text)
    for mode, phrases in config.MODE_PHRASES.items():
        if phrase in phrases:
            return f"mode_{mode}"
    return None


class Commands:
    async def run(self, kind: str, text: str, say):
        """`say(lines)` speaks fixed lines and waits until they finish (or get interrupted)."""
        if kind == "clip":
            await say(["Clipping!"])
            ok = await asyncio.to_thread(self._make_twitch_clip)
            await say(["Clip made!" if ok else "Clip failed, sorry beep boop."])

    def _make_twitch_clip(self) -> bool:
        import requests
        if not (config.TWITCH_CLIENT_ID and config.TWITCH_USER_TOKEN and config.TWITCH_BROADCASTER_ID):
            log.warning("clip: Twitch settings missing from server/.env")
            return False
        try:
            r = requests.post(
                "https://api.twitch.tv/helix/clips",
                headers={
                    "Client-ID": config.TWITCH_CLIENT_ID,
                    "Authorization": f"Bearer {config.TWITCH_USER_TOKEN}",
                },
                params={"broadcaster_id": config.TWITCH_BROADCASTER_ID},
                timeout=10,
            )
            data = r.json()
            if data.get("data"):
                log.info("clip created: https://clips.twitch.tv/%s", data["data"][0]["id"])
                return True
            log.warning("clip failed: %s", data)
        except Exception as e:
            log.warning("clip error: %s", e)
        return False
