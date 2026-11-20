// AudioWorklet: runs in a 16 kHz AudioContext and posts 20 ms int16 frames (ARCHITECTURE.md §4.3).
// Plain JS on purpose: it's loaded as a string (?raw) into a Blob URL, so it works from file:// too.
const FRAME = 320

class Pcm16k extends AudioWorkletProcessor {
  constructor() {
    super()
    this.buf = new Int16Array(FRAME)
    this.n = 0
    this.peak = 0
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        const s = Math.max(-1, Math.min(1, ch[i]))
        const a = s < 0 ? -s : s
        if (a > this.peak) this.peak = a
        this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff
        if (this.n === FRAME) {
          this.port.postMessage({ pcm: this.buf.buffer, peak: this.peak }, [this.buf.buffer])
          this.buf = new Int16Array(FRAME)
          this.n = 0
          this.peak = 0
        }
      }
    }
    return true
  }
}

registerProcessor('pcm16k', Pcm16k)
