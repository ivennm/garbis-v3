/** Settings screen (ARCHITECTURE.md §4.5). The window grows while it's open. */
import { useEffect, useState } from 'react'
import type { Settings } from '../../../shared/types'
import { controller } from '../controller'
import { useGarbis } from '../state/store'

interface Devices {
  inputs: MediaDeviceInfo[]
  outputs: MediaDeviceInfo[]
}

function useDevices(): Devices {
  const [devices, setDevices] = useState<Devices>({ inputs: [], outputs: [] })
  useEffect(() => {
    const load = async () => {
      const all = await navigator.mediaDevices.enumerateDevices()
      const real = (d: MediaDeviceInfo) => d.deviceId !== 'default' && d.deviceId !== 'communications'
      setDevices({
        inputs: all.filter((d) => d.kind === 'audioinput' && real(d)),
        outputs: all.filter((d) => d.kind === 'audiooutput' && real(d))
      })
    }
    void load()
    navigator.mediaDevices.addEventListener('devicechange', load)
    return () => navigator.mediaDevices.removeEventListener('devicechange', load)
  }, [])
  return devices
}

/** The saved device, if it isn't plugged in right now (so the picker doesn't pretend it's "System default"). */
function MissingOption({ id, list }: { id: string; list: MediaDeviceInfo[] }) {
  if (!id || list.some((d) => d.deviceId === id)) return null
  return <option value={id}>Saved device (not connected)</option>
}

export default function SettingsPanel() {
  const saved = useGarbis((s) => s.settings)
  const level = useGarbis((s) => s.micLevel)
  const micError = useGarbis((s) => s.micError)
  const desktopLevel = useGarbis((s) => s.desktopLevel)
  const desktopLive = useGarbis((s) => s.desktopLive)
  const desktopError = useGarbis((s) => s.desktopError)
  const screenError = useGarbis((s) => s.screenError)
  const conn = useGarbis((s) => s.conn)
  const connDetail = useGarbis((s) => s.connDetail)
  const devices = useDevices()
  const [draft, setDraft] = useState<Settings | null>(saved)

  const [base, setBase] = useState<Settings | null>(saved)
  useEffect(() => {
    // settings changed elsewhere (tray, corner buttons): take them unless the user is mid-edit
    if (saved && (!draft || JSON.stringify(draft) === JSON.stringify(base))) {
      setDraft(saved)
      setBase(saved)
    }
  }, [saved])

  if (!draft || !saved) return null

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => setDraft({ ...draft, [key]: value })
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved)

  const save = async () => {
    await controller.updateSettings(draft)
  }
  const close = async () => {
    if (dirty) await save()
    await controller.openPanel('none')
  }

  return (
    <form
      className="settings"
      onSubmit={(e) => {
        e.preventDefault()
        void close()
      }}
    >
      <h1>Settings</h1>

      <section>
        <h2>Server</h2>
        <label>
          Address
          <input
            type="text"
            value={draft.serverUrl}
            spellCheck={false}
            onChange={(e) => set('serverUrl', e.target.value)}
            placeholder="ws://mc-server:8765/ws"
          />
        </label>
        <label>
          Token
          <input
            type="password"
            value={draft.token}
            autoComplete="off"
            onChange={(e) => set('token', e.target.value)}
            placeholder="GARBIS_TOKEN from server/.env"
          />
        </label>
        <p className={`hint conn-${conn}`}>
          {conn === 'online' ? 'Connected' : conn === 'refused' ? (connDetail ?? 'Refused') : 'Not connected'}
        </p>
      </section>

      <section>
        <h2>Microphone</h2>
        <label>
          Device
          <select value={draft.micDeviceId} onChange={(e) => set('micDeviceId', e.target.value)}>
            <option value="">System default</option>
            <MissingOption id={draft.micDeviceId} list={devices.inputs} />
            {devices.inputs.map((d) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label || 'Microphone'}
              </option>
            ))}
          </select>
        </label>
        <div className="meter" aria-label="mic level">
          <div style={{ width: `${Math.min(100, level * 140)}%` }} />
        </div>
        {micError && <p className="hint error">{micError}</p>}
        <label className="check">
          <input
            type="checkbox"
            checked={draft.echoCancellation}
            onChange={(e) => set('echoCancellation', e.target.checked)}
          />
          Echo cancellation{' '}
          <span className="hint">(only with speakers: it can swallow "stop" while Garbis talks; headphones are best)</span>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.noiseSuppression}
            onChange={(e) => set('noiseSuppression', e.target.checked)}
          />
          Noise suppression
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.autoGainControl}
            onChange={(e) => set('autoGainControl', e.target.checked)}
          />
          Auto gain
        </label>
      </section>

      <section>
        <h2>Desktop audio (guests)</h2>
        <label className="check">
          <input type="checkbox" checked={draft.desktopAudio} onChange={(e) => set('desktopAudio', e.target.checked)} />
          Garbis hears desktop audio <span className="hint">(calls, streams, videos; guests need "garbis")</span>
        </label>
        <label>
          Source
          <select
            value={draft.desktopDeviceId}
            disabled={!draft.desktopAudio}
            onChange={(e) => set('desktopDeviceId', e.target.value)}
          >
            <option value="">System audio</option>
            <MissingOption id={draft.desktopDeviceId} list={devices.inputs} />
            {devices.inputs.map((d) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label || 'Input device'}
              </option>
            ))}
          </select>
        </label>
        <div className="meter" aria-label="desktop audio level">
          <div style={{ width: `${Math.min(100, desktopLevel * 140)}%` }} />
        </div>
        {draft.desktopAudio && desktopError && <p className="hint error">{desktopError}</p>}
        {draft.desktopAudio && !desktopError && (
          <p className="hint">
            {desktopLive
              ? 'Listening. The meter moves when something plays (it stays still while Garbis talks).'
              : 'Starting…'}
          </p>
        )}
      </section>

      <section>
        <h2>Screen vision</h2>
        <label className="check">
          <input type="checkbox" checked={draft.screenVision} onChange={(e) => set('screenVision', e.target.checked)} />
          Garbis can see my main monitor{' '}
          <span className="hint">
            (a small screenshot every 5 s, kept only in the server's memory; he looks only when you ask, like "what am I
            looking at?")
          </span>
        </label>
        {draft.screenVision && screenError && <p className="hint error">{screenError}</p>}
      </section>

      <section>
        <h2>Voice</h2>
        <label>
          Output
          <select value={draft.outputDeviceId} onChange={(e) => set('outputDeviceId', e.target.value)}>
            <option value="">System default</option>
            <MissingOption id={draft.outputDeviceId} list={devices.outputs} />
            {devices.outputs.map((d) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label || 'Speaker'}
              </option>
            ))}
          </select>
        </label>
        <label>
          Volume
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={draft.volume}
            onChange={(e) => set('volume', Number(e.target.value))}
          />
        </label>
      </section>

      <section>
        <h2>Window</h2>
        <label className="check">
          <input type="checkbox" checked={draft.alwaysOnTop} onChange={(e) => set('alwaysOnTop', e.target.checked)} />
          Always on top
        </label>
        <label className="check">
          <input type="checkbox" checked={draft.startInTray} onChange={(e) => set('startInTray', e.target.checked)} />
          Start in the tray <span className="hint">(closing the window always keeps Garbis listening in the tray)</span>
        </label>
      </section>

      <div className="actions">
        <button type="button" disabled={!dirty} onClick={() => void save()}>
          Apply
        </button>
        <button type="submit" className="primary">
          Done
        </button>
      </div>
    </form>
  )
}
