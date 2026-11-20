# Garbis v3

Garbis as a desktop app (Electron, Mac + Windows) with the brain on the home server.
How it works: [ARCHITECTURE.md](ARCHITECTURE.md). The build order (`APP_PLAN.md`) and background (`../PLAN.md`) are local notes, not in the repo.

```
garbis/server/   Python: speech detection, whisper, Ollama, edge-tts, turn logic. Runs on mc-server.
garbis/app/      Electron + React: face, mic, desktop audio, playback. Runs on the Mac / Windows PC.
garbis/bench/    Step 0 benchmarks.
```
All code lives in `garbis/`. In the docs, paths like `server/.env` or `app/dist/` mean `garbis/server/.env` and `garbis/app/dist/`.

---

## 1. Install the server (mc-server, once)

```bash
cd ~/code/projects/garbis/garbis-v3/garbis/server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # paste this as GARBIS_TOKEN in .env
```

Run it as a service so Garbis starts with the server:
```bash
sudo cp garbis.service /etc/systemd/system/garbis.service
sudo systemctl daemon-reload
sudo systemctl enable --now garbis
curl localhost:8765/health        # {"ready": true, "stt_device": "cuda", ...}
```
The unit runs as `iven` from the venv, after Ollama, and restarts on failure. If the code moves, edit the paths in `garbis.service`.

## 2. Install the app (Mac and Windows)

You need Node 26 LTS (nodejs.org) on the machine. From a checkout of the repo:

| | Mac | Windows |
|---|---|---|
| Build | `cd garbis-v3/garbis/app && npm install && npm run dist:mac` | `cd garbis-v3\garbis\app && npm install && npm run dist:win` |
| Result | `garbis/app/dist/Garbis-0.1.0-arm64.dmg` (Apple Silicon; `-x64` on Intel): open it, drag Garbis to Applications | `garbis\app\dist\Garbis Setup 0.1.0.exe`: run it |
| First launch | Built locally, so no download warning. If macOS still blocks it: right-click → Open | SmartScreen may warn ("unknown publisher"): More info → Run anyway |

The Mac build is ad-hoc signed (no Apple certificate), so macOS may ask for the mic and system-audio permissions again after a rebuild.

**First run:**
1. Click the **gear** (top right). Set **Address** to `ws://mc-server:8765/ws` (that's the default; it works at home and over Tailscale) and **Token** to the `GARBIS_TOKEN` from `server/.env`.
2. Allow the **microphone** when asked.
3. Mac: allow **System Audio Recording** when asked, so Garbis hears guests. If it's blocked, the corner speaker icon turns red and settings say where to allow it.
4. Use **headphones**. Echo cancellation is off by default because it swallowed "stop" while Garbis talked; turn it on only if you use speakers.

**Day to day:**
- **Closing the window doesn't quit Garbis.** He keeps listening from the tray / menu bar icon. Quit from its menu, or Cmd+Q on the Mac. "Start in the tray" is in the same menu.
- Corner controls: connection dot, **LOW/HIGH** mode, mute mic, desktop audio (guests), transcript, settings.
- Voice: "hey garbis …", "garbis, stop", "garbis think hard" (high mode), "garbis chill" (low mode), "garbis clip that".
- Open on a second device: it takes over (the first shows **Use here**). Close it, and the first takes back over by itself.

**Desktop audio fallback (Mac):** if system audio capture won't work, install [BlackHole](https://existential.audio/blackhole/) (2ch). Make a Multi-Output Device in Audio MIDI Setup (your speakers/headphones + BlackHole) and use it as the system output. Then pick **BlackHole 2ch** as the desktop audio **Source** in Garbis's settings.

## 3. Troubleshooting

| Problem | Check |
|---|---|
| Face is grey, "Can't reach the server" | `systemctl status garbis`; `curl mc-server:8765/health` from that machine; `tailscale ping mc-server` |
| "wrong token" | The app's token must match `GARBIS_TOKEN` in `server/.env` (restart the service after changing it) |
| Garbis says "My brain server isn't answering" | `systemctl status ollama`; `ollama ps` |
| Slow first answer after a long break | Normal: the model unloads after 60 min idle and takes a few seconds to load again |
| He mishears "garbis" | Add the mishearing to `MISHEARD_GARBIS` in `server/garbis_server/config.py` (see the transcript or the logs) |
| "stop" doesn't stop him | Headphones, and echo cancellation **off** (settings) |
| Logs | `journalctl -u garbis -f` (every heard phrase, the action, and a `[timing]` line per reply) |
| Reset Garbis's memory | `sudo systemctl stop garbis`, delete `server/data/memory.json` (and `state.json` for the mode), start it again |

`/health` shows `ready`, `mode`, `model`, `stt_device` (`cuda`, or `cpu` if the GPU load failed), the active device, and the memory size.

---

## Development

### Server
```bash
cd garbis-v3/garbis/server
.venv/bin/python -m garbis_server        # in the foreground, instead of the service (stop the service first)
.venv/bin/python -m pytest -q            # tests
```
- **Browser test page (no app):** on the Mac, run `ssh -L 8765:localhost:8765 mc-server` and open `http://localhost:8765/test`. The mic only works on localhost or HTTPS, which is why it goes through the tunnel.
- **Smoke test with recorded speech:** `.venv/bin/python tools/talk.py ../bench/samples/short.wav`. Also try `--source desktop`, `--mode high`, or `--stop-after 1 ../bench/samples/long.wav ../bench/samples/stop.wav`.
- **Don't touch real memory while testing:** set `GARBIS_DATA_DIR=/tmp/garbis-test`.
- Whisper runs on the GPU in int8 and must load before Ollama loads a model; the server does this at startup. It loads from the local cache, so booting without internet is fine.

### App
On the server (type-check, tests, build; Electron can't show a window here):
```bash
cd garbis-v3/garbis/app
npm install
npm run typecheck && npm test && npm run build
```
Node comes from nvm (`~/.nvm`, Node 26 LTS). In a new shell, run `source ~/.nvm/nvm.sh` if `node` isn't found.

On the Mac or PC: `npm install && npm run dev`. Give each machine its own `node_modules`; never copy them between OSes.
- **Desktop audio under `npm run dev` on the Mac** usually doesn't work: macOS asks on behalf of Terminal/VS Code. Test it with the packaged app, or with BlackHole as the source.
- If `npm run dev` fails with "bad option", the terminal has `ELECTRON_RUN_AS_NODE=1` set. Run `env -u ELECTRON_RUN_AS_NODE npm run dev`.

**Headless check on the server** (no screen; a WAV file acts as the mic; saves a screenshot every second):
```bash
cd garbis-v3/garbis/app && npm run build
env -u ELECTRON_RUN_AS_NODE GARBIS_SCREENSHOT_DIR=/tmp/garbis-shots ./node_modules/electron/dist/electron \
  --ozone-platform=headless --ozone-override-screen-size=1440,900 --no-sandbox --disable-gpu \
  --use-fake-ui-for-media-stream --use-fake-device-for-media-stream \
  "--use-file-for-fake-audio-capture=../bench/samples/short.wav%noloop" .
```
- `GARBIS_SCREENSHOT_CLICK="2:Show transcript"` clicks the button with that title at screenshot 2 (also `Settings`).
- The screenshot hook only exists in unpackaged builds, and the tray is skipped when headless.
- `npx electron-builder --linux dir` builds a packaged copy in `dist/linux-unpacked/` to run the same way. That's the only way to test packaged-only paths here.

Icons are drawn by `garbis/app/scripts/make_icons.py` (needs Pillow). Rerun it after changing the look.
