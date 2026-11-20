import { useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import Controls from './components/Controls'
import Face from './components/Face'
import SettingsPanel from './components/SettingsPanel'
import StatusLine from './components/StatusLine'
import Transcript from './components/Transcript'
import { controller } from './controller'
import { describe, useGarbis } from './state/store'

export default function App() {
  const panel = useGarbis((s) => s.panel)
  const { view, status } = useGarbis(useShallow((s) => describe(s)))

  useEffect(() => {
    void controller.start()
  }, [])

  if (panel === 'settings') return <SettingsPanel />

  const face = (
    <main className={`garbis ${panel === 'transcript' ? 'garbis-compact' : ''}`}>
      <Controls />
      <Face view={view} />
      <StatusLine view={view} status={status} />
    </main>
  )

  if (panel === 'transcript') {
    return (
      <div className="with-transcript">
        {face}
        <Transcript />
      </div>
    )
  }
  return face
}
