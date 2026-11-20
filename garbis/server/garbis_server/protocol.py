"""
Wire format between the app and the server (ARCHITECTURE.md §5). app/src/renderer/src/net/protocol.ts mirrors this.

Binary frames start with a 1-byte type. JSON messages are text frames: {"type": ..., ...}.
"""
import struct

import numpy as np

# binary frame types
MIC = 0x01          # app -> server: 16 kHz mono int16 LE, 20 ms per frame
DESKTOP = 0x02      # app -> server: same, desktop audio
SCREEN = 0x03       # app -> server: u32 request_id (0 = the regular one), JPEG of the main monitor
CLIP = 0x10         # server -> app: u32 turn_id, u16 seq, mp3 bytes

AUDIO_SOURCES = {MIC: "mic", DESKTOP: "desktop"}
_CLIP_HEADER = struct.Struct("<BIH")


def parse_audio(data: bytes) -> tuple[str, np.ndarray] | None:
    """Returns (source, float32 samples in -1..1), or None if the frame isn't audio."""
    if len(data) < 3 or data[0] not in AUDIO_SOURCES or (len(data) - 1) % 2:
        return None
    samples = np.frombuffer(data, dtype="<i2", offset=1).astype(np.float32) / 32768.0
    return AUDIO_SOURCES[data[0]], samples


_SCREEN_HEADER = struct.Struct("<BI")
MAX_SCREENSHOT_BYTES = 2_000_000


def parse_screen(data: bytes) -> tuple[int, bytes] | None:
    """Returns (request_id, jpeg) for a screenshot frame, or None."""
    if len(data) <= _SCREEN_HEADER.size or data[0] != SCREEN or len(data) > MAX_SCREENSHOT_BYTES:
        return None
    _, request_id = _SCREEN_HEADER.unpack_from(data)
    jpeg = data[_SCREEN_HEADER.size:]
    return (request_id, jpeg) if jpeg[:2] == b"\xff\xd8" else None   # JPEG magic


def pack_screen(request_id: int, jpeg: bytes) -> bytes:
    """Test helper: what the app sends."""
    return _SCREEN_HEADER.pack(SCREEN, request_id) + jpeg


def pack_clip(turn_id: int, seq: int, mp3: bytes) -> bytes:
    return _CLIP_HEADER.pack(CLIP, turn_id, seq) + mp3


def unpack_clip(data: bytes) -> tuple[int, int, bytes]:
    kind, turn_id, seq = _CLIP_HEADER.unpack_from(data)
    if kind != CLIP:
        raise ValueError("not a clip frame")
    return turn_id, seq, data[_CLIP_HEADER.size:]


def pack_audio(source: int, samples_int16: np.ndarray) -> bytes:
    """Test helper: what the app sends."""
    return bytes([source]) + samples_int16.astype("<i2").tobytes()
