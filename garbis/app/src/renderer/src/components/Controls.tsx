/** Small corner controls that don't change v2's look: connection dot, LOW/HIGH, mute, desktop audio, transcript, settings. */
import { controller } from '../controller'
import { useGarbis } from '../state/store'

const CONN_LABEL = {
  online: 'Connected',
  connecting: 'Connecting…',
  offline: 'Offline, retrying',
  refused: 'Refused by the server'
} as const

function MicIcon({ muted }: { muted: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
      {muted && <path d="M4 4l16 16" strokeLinecap="round" />}
    </svg>
  )
}

function SpeakerIcon({ off }: { off: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M4 9h4l5-4v14l-5-4H4z" strokeLinejoin="round" />
      {off ? <path d="M17 9l5 6M22 9l-5 6" strokeLinecap="round" /> : <path d="M17 8.5a5 5 0 0 1 0 7M19.5 6a8.5 8.5 0 0 1 0 12" strokeLinecap="round" />}
    </svg>
  )
}

function ListIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M8 6h12M8 12h12M8 18h12" strokeLinecap="round" />
      <circle cx="4" cy="6" r="1" fill="currentColor" />
      <circle cx="4" cy="12" r="1" fill="currentColor" />
      <circle cx="4" cy="18" r="1" fill="currentColor" />
    </svg>
  )
}

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <circle cx="12" cy="12" r="3" />
      <path
        d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export default function Controls() {
  const conn = useGarbis((s) => s.conn)
  const active = useGarbis((s) => s.active)
  const mode = useGarbis((s) => s.mode)
  const modeStatus = useGarbis((s) => s.modeStatus)
  const model = useGarbis((s) => s.model)
  const muted = useGarbis((s) => s.muted)
  const desktopOn = useGarbis((s) => s.settings?.desktopAudio ?? false)
  const desktopLive = useGarbis((s) => s.desktopLive)
  const desktopError = useGarbis((s) => s.desktopError)
  const transcriptOpen = useGarbis((s) => s.panel === 'transcript')

  const canSwitch = conn === 'online' && active && modeStatus === 'ready'
  const other = mode === 'low' ? 'high' : 'low'

  return (
    <div className="controls">
      <span className={`dot dot-${conn}`} title={CONN_LABEL[conn]} aria-label={CONN_LABEL[conn]} />
      <button
        className={`badge badge-${mode}`}
        disabled={!canSwitch}
        onClick={() => controller.setMode(other)}
        title={modeStatus === 'loading' ? `Loading ${model}…` : `${model} · click for ${other} mode`}
      >
        {mode.toUpperCase()}
      </button>
      <button
        className={`icon ${muted ? 'icon-on' : ''}`}
        onClick={() => controller.toggleMute()}
        title={muted ? 'Unmute mic' : 'Mute mic'}
        aria-pressed={muted}
      >
        <MicIcon muted={muted} />
      </button>
      <button
        className={`icon ${desktopOn && desktopError ? 'icon-on' : desktopLive ? 'icon-live' : ''}`}
        onClick={() => void controller.toggleDesktop()}
        title={
          !desktopOn
            ? 'Desktop audio off: click so Garbis hears guests'
            : (desktopError ?? (desktopLive ? 'Hearing desktop audio (guests): click to stop' : 'Starting desktop audio…'))
        }
        aria-pressed={desktopOn}
      >
        <SpeakerIcon off={!desktopOn} />
      </button>
      <button
        className={`icon ${transcriptOpen ? 'icon-active' : ''}`}
        onClick={() => void controller.togglePanel('transcript')}
        title={transcriptOpen ? 'Hide transcript' : 'Show transcript'}
        aria-pressed={transcriptOpen}
      >
        <ListIcon />
      </button>
      <button className="icon" onClick={() => void controller.openPanel('settings')} title="Settings">
        <GearIcon />
      </button>
    </div>
  )
}
