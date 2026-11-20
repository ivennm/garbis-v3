"""Make test phrases with edge-tts at normal speed (16 kHz mono WAV)."""
import asyncio, subprocess, pathlib
import edge_tts

PHRASES = {
    "stop": "Garbis, stop.",
    "short": "Hey Garbis, what's two plus two?",
    "medium": "Hey Garbis, can you tell me what the weather is going to be like tomorrow afternoon?",
    "long": ("Garbis, I just finished a really long match and my team kept running off on their own, "
             "so give me three tips for getting people to actually stick together and play the objective."),
}

async def main():
    out = pathlib.Path(__file__).parent / "samples"
    for name, text in PHRASES.items():
        mp3 = out / f"{name}.mp3"
        await edge_tts.Communicate(text, "en-US-GuyNeural").save(str(mp3))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "16000", "-ac", "1",
                        str(out / f"{name}.wav")], check=True)
        mp3.unlink()
    (out / "phrases.txt").write_text("\n".join(f"{k}\t{v}" for k, v in PHRASES.items()) + "\n")

asyncio.run(main())
