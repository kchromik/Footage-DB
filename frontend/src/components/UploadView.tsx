import { useRef, useState } from 'react'
import { useUploader } from '../lib/uploader'
import { formatBytes } from '../lib/format'
import { IconClose, IconRefresh, IconUpload } from './Icons'

interface Props {
  organizeUploads: boolean
  pattern: string
  onUploaded: (clipId: number) => void
}

export function UploadView({ organizeUploads, pattern, onUploaded }: Props) {
  const [over, setOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const { tasks, add, cancel, retry, clearFinished, active } = useUploader(onUploaded)

  const pickFiles = (list: FileList | null) => {
    if (!list || list.length === 0) return
    add(Array.from(list))
  }

  return (
    <div className="view">
      <div className="view-head">
        <h2>Footage hochladen</h2>
        <p>
          Dateien werden blockweise uebertragen. Bricht die Verbindung ab, macht der
          naechste Versuch an derselben Stelle weiter.
          {organizeUploads
            ? ` Neue Dateien werden automatisch nach ${pattern} einsortiert.`
            : ' Neue Dateien landen im Wurzelordner der Bibliothek.'}
        </p>
      </div>

      <div
        className={`dropzone${over ? ' over' : ''}`}
        onDragOver={(event) => {
          event.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault()
          setOver(false)
          pickFiles(event.dataTransfer.files)
        }}
      >
        <IconUpload size={30} />
        <h3>Dateien hierher ziehen</h3>
        <p>oder per Knopf auswaehlen. Mehrere Dateien gleichzeitig sind moeglich.</p>
        <button className="btn primary" onClick={() => inputRef.current?.click()}>
          Dateien auswaehlen
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="video/*,.mp4,.mov,.mxf,.mts,.m2ts,.avi,.mkv,.m4v,.braw,.r3d"
          hidden
          onChange={(event) => {
            pickFiles(event.target.files)
            event.target.value = ''
          }}
        />
      </div>

      {tasks.length > 0 && (
        <div className="card-block" style={{ marginTop: 18 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: 6,
            }}
          >
            <h3 style={{ margin: 0 }}>
              Uebertragung {active && <span className="spinner" style={{ display: 'inline-block', verticalAlign: -2, marginLeft: 6 }} />}
            </h3>
            <button className="btn ghost small" onClick={clearFinished}>
              Fertige ausblenden
            </button>
          </div>

          {tasks.map((task) => {
            const percent = task.total ? Math.round((task.sent / task.total) * 100) : 0
            return (
              <div className="upload-row" key={task.key}>
                <div className="fname" title={task.targetPath ?? task.file.name}>
                  {task.file.name}
                  {task.targetPath && (
                    <span
                      className="mono"
                      style={{ color: 'var(--text-faint)', fontSize: 10, marginLeft: 8 }}
                    >
                      {task.targetPath}
                    </span>
                  )}
                  {task.error && (
                    <span style={{ color: 'var(--danger)', fontSize: 11, marginLeft: 8 }}>
                      {task.error}
                    </span>
                  )}
                </div>
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{
                      width: `${task.state === 'fertig' ? 100 : percent}%`,
                      background:
                        task.state === 'fehler'
                          ? 'var(--danger)'
                          : task.state === 'fertig'
                            ? 'var(--look-graded)'
                            : undefined,
                    }}
                  />
                </div>
                <div
                  className={`state${task.state === 'fertig' ? ' done' : ''}${
                    task.state === 'fehler' ? ' error' : ''
                  }`}
                >
                  {task.state === 'laeuft'
                    ? `${percent}%`
                    : task.state === 'fertig'
                      ? formatBytes(task.total)
                      : task.state}
                </div>
                <div>
                  {task.state === 'fehler' || task.state === 'abgebrochen' ? (
                    <button
                      className="btn ghost small"
                      onClick={() => retry(task.key)}
                      aria-label="Erneut versuchen"
                    >
                      <IconRefresh size={12} />
                    </button>
                  ) : task.state !== 'fertig' ? (
                    <button
                      className="btn ghost small"
                      onClick={() => cancel(task.key)}
                      aria-label="Abbrechen"
                    >
                      <IconClose size={12} />
                    </button>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
