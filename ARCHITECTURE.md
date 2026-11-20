# Garbis v3: Architecture

This describes how Garbis v3 works. The build order (`APP_PLAN.md`) and the background decisions and benchmarks (`../PLAN.md`) are local notes, not part of the repo.

Decided 2026-11-19.

---

## 1. The big picture

```
 Mac / Windows                                   Linux server (mc-server, GTX 1650 4 GB)
┌──────────────────────────────┐               ┌────────────────────────────────────────────┐
│ Garbis app (Electron + React)│   WebSocket   │ garbis-server (Python, FastAPI, one process)│
│                              │  ws://…:8765  │                                            │
│  mic ──► AudioWorklet 16 kHz ├──── 0x01 ────►│ VAD (mic) ─┐                               │
│  desktop loopback ──► 16 kHz ├──── 0x02 ────►│ VAD (desk) ┴► whisper ► Conversation       │
│                              │               │                  base.en      │  (turn logic)│
│  face · status · transcript ◄├── JSON ───────┤ state / heard / say / mode    ▼             │
│  player (Web Audio)         ◄├──── 0x10 ─────┤ edge-tts ◄── sentences ◄── Brain ──► Ollama │
│        └─ clip_started/ended ├──── JSON ────►│ RemotePlayer (waits for clip reports)  :11434│
└──────────────────────────────┘               │ Memory (data/memory.json)                   │
                                               └────────────────────────────────────────────┘
```

**The app is only the face, ears and mouth.** It captures audio, plays audio, and draws the face. Everything that decides anything runs on the server: speech detection, transcription, turn-taking, interruptions, the LLM, memory, TTS and commands. Changing Garbis's behavior never requires reinstalling the app.

**Only one app is active at a time.** The most recently connected app takes over. The others show "Garbis is active on <device>" and a "Use here" button.

---

## 2. Repository layout

```
garbis-v3/
├── ARCHITECTURE.md · README.md · .gitignore   (APP_PLAN.md: local only, git-ignored)
└── garbis/                     all the code
    ├── bench/                      step 0 benchmarks (done)
    ├── server/
    │   ├── requirements.txt · .env.example · garbis.service
    │   ├── garbis_server/
    │   │   ├── main.py             FastAPI app: startup order, /ws, /health, /test
    │   │   ├── config.py           every setting, personalities, MODES (+ .env)
    │   │   ├── protocol.py         message names, binary frame types, (de)serializers
    │   │   ├── session.py          SessionManager: one active connection, takeover
    │   │   ├── conversation.py     v2 turn engine, ported (see §6)
    │   │   ├── remote.py           RemotePlayer, RemoteUI: the app seen as a player and a face
    │   │   ├── vad.py              v2, unchanged
    │   │   ├── stt.py              faster-whisper on the GPU (int8), CPU fallback
    │   │   ├── brain.py            Ollama streaming, modes, cache-friendly prompts, re-priming
    │   │   ├── memory.py           chat-message memory, saved to disk
    │   │   ├── speech.py           SentenceSplitter + text cleanup for TTS (emoji, markdown, math)
    │   │   ├── tts.py              edge-tts → mp3 bytes
    │   │   └── commands.py         "clip that", mode switching
    │   ├── static/test.html        browser test page (mic in, voice out, no Electron)
    │   ├── data/                   memory.json, state.json (git-ignored)
    │   └── tests/                  pytest
    └── app/
        ├── package.json · electron.vite.config.ts · electron-builder.yml · tsconfig*.json
        ├── resources/              icon.png / icon.icns / icon.ico, tray icons
        └── src/
            ├── main/               Electron main process
            │   ├── index.ts        window, tray, lifecycle, single-instance lock
            │   ├── desktopAudio.ts setDisplayMediaRequestHandler (loopback audio)
            │   ├── settings.ts     settings.json in userData
            │   └── permissions.ts  macOS mic / system-audio permission prompts
            ├── preload/index.ts    contextBridge: settings, app info, window controls
            ├── shared/types.ts     types shared by main, preload and renderer
            └── renderer/           React (index.html + src/)
                ├── App.tsx
                ├── components/     Face.tsx, StatusLine.tsx, ModeBadge.tsx, Transcript.tsx,
                │                   Settings.tsx, InactiveBanner.tsx
                ├── audio/          mic.ts, desktop.ts, pcm16k.worklet.ts, player.ts, levels.ts
                ├── net/            socket.ts (reconnecting WS), protocol.ts (mirrors protocol.py)
                └── state/store.ts  app state (zustand)
```

---

## 3. Server

### 3.1 Process and threads
A single `uvicorn` process with one asyncio loop:

| Work | Where it runs | Notes |
|---|---|---|
| WebSocket I/O, VAD, turn logic, Ollama streaming, edge-tts | asyncio loop | VAD costs under 1 ms per 32 ms frame |
| whisper | one-thread executor | Mic phrases get priority. Desktop phrases are skipped while whisper is busy (same as v2) |
| Saving memory and state to disk | `asyncio.to_thread` | Atomic write: temp file, then rename |

### 3.2 Startup order (matters because of GPU memory)
1. Load whisper `base.en` on the **GPU in int8** and transcribe 1 s of silence to warm it up. If the GPU load fails, fall back to the CPU (int8, 4 threads, about 0.6 s per phrase) and log a warning.
2. Load `data/memory.json` and `data/state.json`, which hold the last mode.
3. Warm up the current mode's model (`keep_alive: 60m`), then **re-prime** it: send the full prompt with `num_predict: 1` so Ollama caches it. If Ollama is down, the server starts anyway, and Garbis says his brain isn't answering until it's back.
4. Start accepting WebSocket connections. `/health` reports `ready` from here on.

Whisper must load before Ollama loads a model. Otherwise the 8B fallback can take all the video memory (PLAN.md §8).

### 3.3 Endpoints
| Path | Purpose |
|---|---|
| `GET /health` | `{ready, mode, model, stt_device, active_device, version}` |
| `WS /ws` | the app protocol (§5) |
| `GET /test` | browser test page (§3.6) |

The server binds to `0.0.0.0:8765`, which is only reachable on the LAN or over Tailscale and never port-forwarded. The `hello` message must carry `GARBIS_TOKEN` from the server's `.env`. It's a shared secret that stops anything else on the network from driving Garbis. If `GARBIS_TOKEN` is empty, any device on the network can connect, and the server logs a warning at startup.

### 3.4 Sessions (one active app)
`SessionManager` keeps every open connection, but only one is **active**:
- When a new app connects and sends `hello`, it becomes active. The previously active app gets `session {active: false, active_device}`.
- An inactive app can send `take_over` to become active again.
- Audio from inactive connections is dropped. Only the active app gets `state`, `heard`, `say`, audio and `mode` messages. Inactive apps get `session` updates only.
- If the active app disconnects, any running turn is cancelled and the state goes to idle. **The most recently connected remaining app becomes active by itself.** If no app is left, nobody is active until one connects. (Changed 2026-11-19: otherwise a lone app kept saying "active on another device".)

### 3.5 Remote proxies
v2's `conversation.py` talks to a `ui` and a `player`. v3 keeps that shape and puts the network behind it:

- **`RemoteUI.set_state(state, source)`** sends `state` to the active app.
- **`RemotePlayer`** replaces pygame. Its API:
  - `enqueue(turn_id, seq, text, mp3, on_start)` sends `say` and then the binary clip straight away, without waiting for the previous clip to finish. The app queues clips, so there's no network gap between sentences.
  - `on_start` fires when the app reports `clip_started` for that `(turn_id, seq)`. That's when the sentence counts as "said" for memory, same as v2.
  - `finish(turn_id)` sends `turn_end` and waits until the app reports `clip_ended` for the last clip.
  - `stop(turn_id)` sends `stop_audio`. Cancelling the turn task calls it.
  - `active` is true from the first `enqueue` until the last `clip_ended` or `stop`. `last_audio_end` keeps v2's meaning.
  - **Safety timeout:** if a `clip_ended` never arrives, the clip is treated as ended at its mp3 duration + 3 s. edge-tts mp3 is 48 kbit/s, so duration = bytes × 8 / 48000. A lost message can't freeze Garbis.

### 3.6 Browser test page
`static/test.html` is a single file with no build step. It does mic capture (same AudioWorklet idea as the app), plays clips, and shows state and transcript. It exists so the server can be built and tested before the Electron app.

Browsers only allow the mic on a **secure origin**. Open it through an SSH tunnel (`ssh -L 8765:localhost:8765 mc-server`, then `http://localhost:8765/test`) or through `tailscale serve` over HTTPS.

---

## 4. App

### 4.1 Stack
- **Electron + electron-vite + React + TypeScript**, with electron-builder for packaging. Exact versions are pinned when the project is created.
- **Development:** the code lives on the server (edited over SSH). Node is installed there for type-checking, unit tests and builds. **Electron itself runs on the Mac or the PC** (`npm run dev` in a checkout), because the server has no screen.

### 4.2 Processes
| Process | Does |
|---|---|
| **main** | One window (default 500×180, resizable, background `#1e1e2f`, native title bar) with three layouts: face, face + transcript, settings. **Closing it hides it; Garbis keeps listening.** Tray icon: status, show/hide, mode, mute mic, desktop audio, transcript, start in the tray, quit. Single-instance lock. Settings file. Desktop-audio request handler. macOS permission prompts. |
| **preload** | `window.garbis` = `{appInfo, getSettings, setSettings, setLayout, setTrayState, onTrayAction, onSettingsChanged}` through `contextBridge`. `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`. The renderer owns the socket and audio, so tray clicks are sent to it as actions, and it pushes the state the tray menu shows. |
| **renderer** | Everything else: WebSocket, audio capture and playback, face, settings screen, transcript. |

Set `backgroundThrottling: false` on the window. Garbis has to keep listening and talking while the window is minimized or hidden in the tray.

### 4.3 Audio in
**Mic:** `getUserMedia({audio: {deviceId, echoCancellation, noiseSuppression, autoGainControl, channelCount: 1}})` feeds an `AudioContext({sampleRate: 16000})`. Chromium resamples the input itself, then the `pcm16k` AudioWorklet runs:
- It collects 320 samples (20 ms), converts them to int16, and posts them to the renderer.
- The renderer sends each 20 ms block as binary frame `0x01`.
- Defaults: echo cancellation **off** (like v2; use headphones), noise suppression on, auto gain **off**. All three are settings. *Changed 2026-11-19:* in testing, Chromium's echo canceller swallowed "garbis, stop" while Garbis was talking (it suppresses your voice while the far end plays). With it off, the same phrase stopped him at once.

**Desktop:** the main process registers `session.setDisplayMediaRequestHandler`, which answers with the primary screen plus `audio: 'loopback'`. The renderer calls `getDisplayMedia({audio: true, video: true})`, stops the video track at once, and sends the audio through the same worklet as frame `0x02`. There's no picker or prompt each session.
- **Windows:** WASAPI loopback. Expected to work.
- **macOS:** since Electron 39, Chromium's **CoreAudio Tap** does loopback by default on macOS 14.2+ (the Mac is on 26), with no feature flags. It needs `NSAudioCaptureUsageDescription` in Info.plist and the System Audio Recording permission. If the permission is missing, the audio track arrives already "ended" and is silent, with no error; the app checks for that. Under `npm run dev`, macOS asks on behalf of Terminal or VS Code, which lack the key, so it only works reliably in the packaged app. This is the least proven part. **Fallback:** a "desktop audio device" setting that captures a BlackHole input with `getUserMedia` instead.

**Echo gating in the app:** the app knows exactly when it's playing Garbis's voice, so it **doesn't send desktop frames while a clip is playing or for `DESKTOP_TAIL_S` afterwards**. That keeps Garbis from hearing his own voice through loopback. The server keeps v2's mute rule as a backup.

**Mic mute** (tray, or a button on the window): the app stops sending `0x01`. The face shows a muted marker.

### 4.4 Audio out
`player.ts` uses its own `AudioContext` at the default rate, with an optional output device through `setSinkId`.
- **Queue per turn:** on each binary `0x10` clip it decodes the mp3 with `decodeAudioData` and plays clips in `seq` order, one after another.
- It sends `clip_started` when a clip actually begins and `clip_ended` when it finishes, with `interrupted: true` if it was cut.
- **`stop_audio {turn_id}`** stops the current source at once and drops queued clips for that turn. **`turn_end`** tells it no more clips are coming.
- There's a volume setting (gain node).

### 4.5 Face and window
- **The face matches v2** (see `../refrences/` for the screenshot): the same glyph faces drawn as **SVG**, so they stay sharp at any size, with the same colors and the same blink (30% chance every 3–6 s, 120 ms, in idle or speak).

| State | Face | Color | Status text |
|---|---|---|---|
| idle | `( ⚆ _ ⚆ )` | `#00ccff` | Idle |
| listen | `( ◉ ‿ ◉ )` | `#00ff99` | Listening (mic / desktop) |
| think | `( ◔ _ ◔ )` | `#ffff66` | Thinking... |
| speak | `( ⚆ _ ⚆ )` | `#00ccff` | Speaking |
| blink | `( ◕ ‿ ◕ )` | current color | |
| **new:** disconnected | `( - _ - )` | grey | Can't reach the server, retrying… |
| **new:** inactive | `( ⚆ _ ⚆ )` dimmed | grey | Active on <device> · **Use here** |
| **new:** switching mode | think face | `#ffff66` | Switching brains… |

- **Small extras that don't change the look:** a LOW/HIGH badge in a corner (click it to switch), a connection dot, and a mic-muted icon.
- **Transcript panel:** hidden by default. A toggle grows the window downward. It shows what was heard (source, text, and what Garbis did with it), what Garbis said, and the timing line per reply.
- **Settings screen:** server address, token, mic, desktop audio (on/off, plus a source: system audio or an input device such as BlackHole), output device, volume, the three mic processing switches, always on top (start in the tray comes in M4). There's also a desktop-audio toggle among the corner controls. Settings are stored as `settings.json` in Electron's `userData` folder.

### 4.6 Connection
- **`socket.ts`** reconnects with backoff (0.5 s, doubling up to 5 s). On each connect it sends `hello`. While offline it doesn't send audio and shows the disconnected face.
- **Default server address:** `ws://mc-server:8765/ws`, using the Tailscale MagicDNS name. That works on the LAN and away from home.

---

## 5. Protocol

**One WebSocket per app.** JSON messages are text frames shaped like `{"type": "...", ...}`. Audio uses binary frames that start with a 1-byte type.

### 5.1 Binary frames
| Type | Direction | Layout | Notes |
|---|---|---|---|
| `0x01` | app → server | `u8 type, int16 LE samples` | mic, 16 kHz mono, 320 samples (20 ms) per frame |
| `0x02` | app → server | same | desktop audio |
| `0x03` | app → server | `u8 type, u32 LE request_id, JPEG` | screenshot of the main monitor (768 px wide); `request_id` 0 = the regular one every 5 s |
| `0x10` | server → app | `u8 type, u32 LE turn_id, u16 LE seq, mp3 bytes` | one TTS clip (one sentence) |

Audio upstream is about 32 KB/s per source.

### 5.2 App → server
| Message | Fields | When |
|---|---|---|
| `hello` | `token, device_name, os, app_version, protocol: 1` | first message on every connection |
| `take_over` | | an inactive app clicks "Use here" |
| `set_mode` | `mode: "low" \| "high"` | badge click or tray menu |
| `clip_started` | `turn_id, seq` | a clip begins playing |
| `clip_ended` | `turn_id, seq, interrupted` | a clip finished or was cut |
| `mic_muted` | `muted` | so the server doesn't wait on a muted mic |
| `screen_unavailable` | `request_id, reason` | screen vision is off, or the capture failed (e.g. no macOS permission) |

### 5.3 Server → app
| Message | Fields | Notes |
|---|---|---|
| `welcome` | `server_version, protocol, mode, mode_status` | reply to a valid `hello` |
| `session` | `active, active_device` | sent on connect and whenever the active app changes |
| `state` | `state: idle\|listen\|think\|speak, source?` | drives the face |
| `heard` | `source, text, action` | `action`: `reply`, `ignored`, `stop`, `merged`, `command`, `followup`, `mentioned` |
| `say` | `turn_id, seq, text` | sent just before the `0x10` clip with the same ids |
| `turn_end` | `turn_id` | no more clips for this turn |
| `stop_audio` | `turn_id` | cut playback now |
| `mode` | `mode, status: loading\|ready, model` | |
| `timing` | `turn_id, heard_s, first_text_s, first_audio_s, total_s` | first-audio time comes from `clip_started` |
| `error` | `code, message` | e.g. `bad_token` (then the server closes), `brain_down` |
| `capture_screen` | `request_id` | send a fresh screenshot now (a screen question came in) |

`protocol` is a version number. The app shows "update the app" if the server's version is newer than it understands.

---

## 6. Conversation engine (ported from v2)

**This behavior doesn't change** (v2 `conversation.py`, CHANGELOG v2.2):
- **Wake word:** "garbis", with fuzzy fixes for mishearings plus "Garbies" / "Garby's".
- **Follow-up window:** 3 s from the mic with no wake word (4 s in v2). It only opens if Garbis actually said something.
- **Addressed vs. mentioned (v3, 2026-11-20):** "garbis" in the first 3 or last 2 words (or in a short phrase) means you're talking *to* him, so he answers. "garbis" mid-sentence means he was mentioned in passing: a quick YES/NO check with the same prompt prefix (so the cache holds, about 0.2 s) decides whether to chime in (funny, or a question he can answer). On NO he stays silent: no thinking face, no memory, no follow-up window. The `heard` action is `mentioned`. Low mode uses a rubric prompt; high mode a stricter one (qwen was too eager with the rubric).
- **Stop phrases** cut Garbis off. **Anything else said while he talks is ignored.**
- **Merging:** "garbis" … "what's 5+5" becomes one question if he hasn't started speaking yet.
- **Desktop audio** always needs the wake word and never interrupts Garbis.
- **One turn is one cancellable task** with three workers: brain → TTS (up to 2 sentences ahead) → player. Cancelling the turn closes the Ollama stream, drops TTS work and sends `stop_audio`.

**What changes in v3:**
| Area | v2 | v3 |
|---|---|---|
| Player | pygame `play()` blocks per clip | `RemotePlayer.enqueue()` per clip, then `finish()` (§3.5) |
| UI | tkinter queue | `RemoteUI` → `state` messages |
| Prompt | personality + `str(memory dict)` in the system prompt | one fixed system prompt + memory as chat messages (§7) |
| Model | one model | `low` / `high` modes (§8) |
| Text → TTS | basic emoji/markdown strip | plus spoken math and symbols (§9) |
| Logging | `print` | `logging`, same `[timing]` line |
| New | | `heard.action` and `timing` messages for the transcript panel |
| Wake word | anywhere in the phrase | addressed → answer; mentioned mid-sentence → he decides whether to chime in |
| Text → TTS | | roleplay actions like `*whirs and beeps*` are dropped, not read out |
| Screen vision | none | §8a |
| Hearing "garbis" | junk filter + mishearing list | plus any 5–8 letter "garb…" word, and whisper is primed with `initial_prompt` "Talking to Garbis the robot." (weak-mic test: name kept 4/4 instead of 0/4, no false wake-ups) |

---

## 7. Prompt and memory

Ollama can reuse its cache only if **the start of the prompt doesn't change** between turns (measured in PLAN.md §5: 0.3 s vs 2.4 s to first word).

**One system prompt for both sources.** v2 switched personalities between mic and desktop, which would throw away the cache every time a guest spoke. v3 uses one system prompt per mode:

```
[Garbis base personality: the shared parts of PERSONALITY_MIC / _DESKTOP]
Messages starting with "[guest]" come from desktop audio: someone else (a video, stream, call or game).
Treat them as a guest and be politely playful. All other messages are your owner,
Supreme Master Leader Sama, talking through the microphone.
[mode suffix]
```

The "make up a number" sentence is **only in low mode** (PLAN.md §5).

**Memory is chat messages:** `[system, user, assistant, user, assistant, …, new user]`.
- Desktop questions are stored as `"[guest] …"`.
- An interrupted reply is stored as what was actually said, plus ` ... [you got interrupted here]`, same as v2.
- **The list is only ever appended to.** When it goes over `MEMORY_SIZE` exchanges (10), the oldest half is dropped in one go, and the cache is re-primed in the background as soon as Garbis is idle.
- **Saved to `data/memory.json`** after every turn, and reloaded and re-primed at startup.
- **Memory is shared across modes.** A mode switch rebuilds the system prompt, which is a cache miss anyway because the model changes.

---

## 8. Modes and models

| Mode | Model | `num_ctx` | Temperature | `num_predict` | Notes |
|---|---|---|---|---|---|
| low | `llama3.2` (the 3B) | 4096 | 0.9 | 250 | keeps "make up a number" |
| high | `qwen3:4b-instruct` | 4096 | 0.5 | 400 | high-mode suffix (accuracy, spoken style, one step of working for math) |

- **Every request uses `think: false` and `keep_alive: 60m`.** Only instruct builds are allowed (PLAN.md §5).
- **Switching** happens from the badge, the tray, or the mic only ("garbis think hard" / "garbis high mode" for high, "garbis chill" / "garbis low mode" for low):
  1. Send `mode {status: loading}` and say "switching brains, beep boop".
  2. Load the new model with an empty request. `OLLAMA_MAX_LOADED_MODELS=1` unloads the old one, and the swap takes 2–5 s.
  3. Re-prime memory with the new system prompt, then send `mode {status: ready}`.
  4. Save the mode to `data/state.json`.
- **A question asked during the switch** just waits for the model to finish loading. Nothing else is needed.

---

## 8a. Screen vision (added 2026-11-20)

- **Always watching, looking on demand.** With screen vision on (default; the eye icon in the corner, settings, the tray), the app sends a 768 px JPEG of the **main monitor** every 5 s. The server keeps only the latest one, in RAM, never on disk, and drops it when the active device changes.
- **Screen questions** (`SCREEN_PHRASES`: "screen", "look at", "what am I looking at", "this game", …) when addressed or in the follow-up window:
  1. The `heard` action is `look`.
  2. Garbis says **"Ooh, let me look, beep boop."** right away.
  3. The server asks for a fresh shot (`capture_screen`; waits 2 s, then falls back to the latest one if under 30 s old).
  4. **qwen3-vl:2b-instruct** answers with its own short prompt and no memory. The answer still goes into memory.
  5. Once Garbis is idle, the mode's model reloads and re-primes in the background.
- **Measured (GTX 1650):** the look line plays about 0.3 s after you stop talking, and the answer comes about 7–8 s after (model swap + reading the image). The next normal answer is back to about 1.4 s.
- **Why not a vision model all the time:** as the everyday low-mode model, qwen3-vl:2b parroted its memory, joked worse and chimed in wrongly (5/8), and a screenshot on every reply added about 4 s per answer. qwen3-vl:4b came back empty (thinking model), qwen2.5vl:3b timed out, and moondream was vague.
- **When he can't look,** the line matches the reason: screen vision off, the macOS Screen Recording permission missing, or the capture failed.

## 9. Text for speech

`speech.py` runs on every chunk from the sentence splitter, before edge-tts:
- Strips emojis, markdown (`*_`#~`, list markers like `1.` and `-`) and extra whitespace (from v2).
- **Spoken symbols:** `≈` → "about", `=` → "equals", `+` → "plus", `×` or `*` between numbers → "times", `/` between numbers → "divided by", `%` → "percent", `$0.05` → "5 cents", `$1.10` → "1 dollar 10".
- A chunk with no letters or digits left is skipped.

The text in `say` is the spoken version, so the transcript shows what Garbis actually said.

---

## 10. Configuration

| Where | What |
|---|---|
| `server/garbis_server/config.py` | Everything about behavior: VAD timings, stop phrases, mishearings, voice, personalities, modes, memory size, port |
| `server/.env` (git-ignored; `.env.example` has placeholders) | `GARBIS_TOKEN`, `OLLAMA_HOST` (default `http://127.0.0.1:11434`), Twitch IDs and token |
| App `settings.json` (per device) | Server address, token, devices, volume, window options |

---

## 11. Security
- The server is reachable only over the LAN or Tailscale, never port-forwarded. Every connection needs the token.
- Secrets live only in `server/.env`, never in the app or in git. PLAN.md §9 lists the old secrets to rotate.
- **Electron hardening:** `contextIsolation`, no `nodeIntegration`, a narrow preload API, a CSP that only allows the app's own files plus `ws:`/`wss:` to the configured server, and `setWindowOpenHandler` denies new windows.

---

## 12. Decision log

| Date | Decision | Why |
|---|---|---|
| 2026-11-18 | Electron (not Tauri), brain on the server | Same Chromium audio stack on Mac and Windows; no reinstall for behavior changes |
| 2026-11-18 | VAD + whisper on the server | Reuses v2's code; raw audio is only about 64 KB/s |
| 2026-11-19 | whisper `base.en`, GPU, int8, loaded first | PLAN.md §7: fast, and leaves room for the LLM |
| 2026-11-19 | High mode = `qwen3:4b-instruct` | PLAN.md §7: 44 tok/s, fully on the GPU, accurate with the high-mode prompt |
| 2026-11-19 | One active app at a time, newest takes over | One conversation and one memory; no GPU contention |
| 2026-11-19 | Memory saved to disk, as chat messages | Survives restarts; cache-friendly |
| 2026-11-19 | One system prompt for mic and desktop, `[guest]` tag | Keeps Ollama's prompt cache when guests speak |
| 2026-11-19 | Clips sent ahead, app queues them | No network gap between sentences |
| 2026-11-19 | App gates desktop audio during playback | The app knows exact playback times; the server can only see them after network delay |
| 2026-11-19 | Code lives on the server; Electron runs on the Mac or PC from a checkout | The server has no screen; you SSH in to edit |
