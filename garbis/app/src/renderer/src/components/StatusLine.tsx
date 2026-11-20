import { controller } from '../controller'
import type { FaceView } from '../state/store'

export default function StatusLine({ view, status }: { view: FaceView; status: string }) {
  return (
    <div className="status" role="status" aria-live="polite">
      <span>{status}</span>
      {view === 'inactive' && (
        <button className="use-here" onClick={() => controller.takeOver()}>
          Use here
        </button>
      )}
    </div>
  )
}
