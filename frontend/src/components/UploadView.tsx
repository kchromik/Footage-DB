import { useRef, useState } from 'react'
import { useUploader } from '../lib/uploader'
import { formatBytes } from '../lib/format'
import { IconClose, IconRefresh, IconUpload } from './Icons'
import { TagPicker } from './TagPicker'

interface Props {
  organizeUploads: boolean
  pattern: string
  onUploaded: (clipId: number) => void
}

export function UploadView({ organizeUploads, pattern, onUploaded }: Props) {
  const [over, setOver] = useState(false)
  const [tags, setTags] = useState<string[]>([])
  const [tagsVersion, setTagsVersion] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const { tasks, add, cancel, retry, clearFinished, active } = useUploader((clipId) => {
    // Neu angelegte Tags sollen beim nächsten Mal in den Vorschlägen stehen
    setTagsVersion((version) => version + 1)
    onUploaded(clipId)
  })

  const pickFiles = (list: FileList | null) => {
    if (!list || list.length === 0) return
    add(Array.from(list), tags)
  }

  return (
    <div className="view">
      <div className="view-head">
        <h2>Footage hochladen</h2>
        <p>
          Dateien werden blockweise übertragen. Bricht die Verbindung ab, macht der
          nächste Versuch an derselben Stelle weiter.
          {organizeUploads
            ? ` Neue Dateien werden automatisch nach ${pattern} einsortiert.`
            : ' Neue Dateien landen im Wurzelordner der Bibliothek.'}
        </p>
      </div>

      <div className="card-block" style={{ marginBottom: 14 }}>
        <div className="label" style={{ marginBottom: 8 }}>
          Tags für diesen Upload
        </div>
        <TagPicker
          value={tags}
          onChange={setTags}
          refreshKey={tagsVersion}
          placeholder="Vorhandenes Tag wählen oder neues anlegen"
        />
        <p className="note">
          Bekommen alle Dateien, die du gleich hinzufügst. Kamera, Auflösung und
          Bildlook vergibt FootageDB ohnehin automatisch, hier geht es um das, was
          nur du weißt: Ort, Projekt, Motiv.
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
        <p>oder per Knopf auswählen. Mehrere Dateien gleichzeitig sind möglich.</p>
        <button className="btn primary" onClick={() => inputRef.current?.click()}>
          Dateien auswählen
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="video/*,.mp4,.mov,.mxf,.mts,.m2ts,.avi,.mkv,.m4v,.braw,.r3d,.insv,.360"
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
              Übertragung {active && <span className="spinner" style={{ display: 'inline-block', verticalAlign: -2, marginLeft: 6 }} />}
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
                  {task.tags.length > 0 && (
                    <span style={{ color: 'var(--amber)', fontSize: 11, marginLeft: 8 }}>
                      {task.tags.join(', ')}
                    </span>
                  )}
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
                  {task.state === 'läuft'
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
