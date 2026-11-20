/**
 * v2's text faces, redrawn as SVG so they stay sharp at any window size (ARCHITECTURE.md §4.5):
 *   idle/speak ( ⚆ _ ⚆ )   listen ( ◉ ‿ ◉ )   think ( ◔ _ ◔ )   blink ( ◕ ‿ ◕ )
 */
import { useEffect, useState } from 'react'
import type { FaceView } from '../state/store'

type Eye = 'side' | 'big' | 'quarter' | 'threeQuarter' | 'closed'
type Mouth = 'flat' | 'smile'

interface Look {
  eye: Eye
  mouth: Mouth
  color: string
}

const GREY = '#6b6b80'

export const LOOKS: Record<FaceView, Look> = {
  idle: { eye: 'side', mouth: 'flat', color: '#00ccff' },
  speak: { eye: 'side', mouth: 'flat', color: '#00ccff' },
  listen: { eye: 'big', mouth: 'smile', color: '#00ff99' },
  think: { eye: 'quarter', mouth: 'flat', color: '#ffff66' },
  switching: { eye: 'quarter', mouth: 'flat', color: '#ffff66' },
  offline: { eye: 'closed', mouth: 'flat', color: GREY },
  inactive: { eye: 'side', mouth: 'flat', color: GREY }
}

const BLINK_EYE: Eye = 'threeQuarter'
const EYE_R = 22

function EyeShape({ cx, cy, kind }: { cx: number; cy: number; kind: Eye }) {
  const r = EYE_R
  if (kind === 'closed') {
    return <line x1={cx - r} y1={cy} x2={cx + r} y2={cy} strokeWidth={6} strokeLinecap="round" />
  }
  return (
    <g>
      <circle cx={cx} cy={cy} r={r} fill="none" strokeWidth={5} />
      {kind === 'side' && <circle cx={cx + 11} cy={cy} r={5} fill="currentColor" stroke="none" />}
      {kind === 'big' && <circle cx={cx} cy={cy} r={11} fill="currentColor" stroke="none" />}
      {kind === 'quarter' && (
        // ◔ upper-right quarter filled
        <path d={`M ${cx} ${cy} L ${cx} ${cy - r} A ${r} ${r} 0 0 1 ${cx + r} ${cy} Z`} fill="currentColor" stroke="none" />
      )}
      {kind === 'threeQuarter' && (
        // ◕ all but the upper-left quarter filled
        <path d={`M ${cx} ${cy} L ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - r} ${cy} Z`} fill="currentColor" stroke="none" />
      )}
    </g>
  )
}

function useBlink(enabled: boolean): boolean {
  const [blinking, setBlinking] = useState(false)
  useEffect(() => {
    if (!enabled) return
    let timer: ReturnType<typeof setTimeout>
    const schedule = () => {
      // v2: every 3-6 s, 30% chance, 120 ms
      timer = setTimeout(
        () => {
          if (Math.random() < 0.3) {
            setBlinking(true)
            timer = setTimeout(() => {
              setBlinking(false)
              schedule()
            }, 120)
          } else {
            schedule()
          }
        },
        3000 + Math.random() * 3000
      )
    }
    schedule()
    return () => {
      clearTimeout(timer)
      setBlinking(false)
    }
  }, [enabled])
  return blinking
}

export default function Face({ view }: { view: FaceView }) {
  const look = LOOKS[view]
  const blinking = useBlink(view === 'idle' || view === 'speak')
  const eye = blinking ? BLINK_EYE : look.eye
  const mouth: Mouth = blinking ? 'smile' : look.mouth

  return (
    <svg
      className="face"
      viewBox="0 0 500 130"
      role="img"
      aria-label={`Garbis face: ${view}`}
      style={{ color: look.color }}
      stroke="currentColor"
      fill="none"
    >
      {/* ( ... ) */}
      <path d="M 78 22 Q 44 65 78 108" strokeWidth={9} strokeLinecap="round" />
      <path d="M 422 22 Q 456 65 422 108" strokeWidth={9} strokeLinecap="round" />
      <EyeShape cx={168} cy={58} kind={eye} />
      <EyeShape cx={332} cy={58} kind={eye} />
      {mouth === 'flat' ? (
        <line x1={222} y1={94} x2={278} y2={94} strokeWidth={8} />
      ) : (
        <path d="M 222 86 Q 250 110 278 86" strokeWidth={6} strokeLinecap="round" />
      )}
    </svg>
  )
}
