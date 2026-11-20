/** What Garbis heard, what he did with it, what he said, and how long it took (M4). */
import { useEffect, useRef } from 'react'
import { controller } from '../controller'
import { clearTranscript, useGarbis } from '../state/store'
import type { Entry } from '../state/store'

const ACTION_LABEL: Record<string, string> = {
  reply: 'answered',
  followup: 'follow-up',
  ignored: 'ignored',
  stop: 'stopped',
  merged: 'merged',
  command: 'command'
}

function time(at: number): string {
  return new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function Line({ e }: { e: Entry }) {
  if (e.kind === 'timing') return <div className="t-timing">{e.text}</div>
  const who =
    e.kind === 'said' ? 'Garbis' : e.kind === 'heard' ? (e.source === 'desktop' ? 'Guest' : 'You') : e.kind === 'error' ? '!' : '·'
  return (
    <div className={`t-line t-${e.kind} ${e.kind === 'heard' && e.action === 'ignored' ? 't-dim' : ''}`}>
      <span className="t-time">{time(e.at)}</span>
      <span className="t-who">{who}</span>
      <span className="t-text">
        {e.text}
        {e.kind === 'heard' && e.action && (
          <span className={`t-action t-action-${e.action}`}>{ACTION_LABEL[e.action] ?? e.action}</span>
        )}
      </span>
    </div>
  )
}

export default function Transcript() {
  const entries = useGarbis((s) => s.transcript)
  const list = useRef<HTMLDivElement>(null)
  const stick = useRef(true) // follow new lines unless the user scrolled up

  useEffect(() => {
    const el = list.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [entries])

  return (
    <section className="transcript" aria-label="Transcript">
      <header>
        <span>Transcript</span>
        <span className="t-buttons">
          <button onClick={clearTranscript} disabled={!entries.length} title="Clear transcript">
            Clear
          </button>
          <button onClick={() => void controller.openPanel('none')} title="Hide transcript">
            Hide
          </button>
        </span>
      </header>
      <div
        className="t-list"
        ref={list}
        onScroll={(ev) => {
          const el = ev.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
        }}
      >
        {entries.length === 0 ? (
          <p className="t-empty">Say "hey garbis…" and the conversation shows up here.</p>
        ) : (
          entries.map((e) => <Line key={e.id} e={e} />)
        )}
      </div>
    </section>
  )
}
