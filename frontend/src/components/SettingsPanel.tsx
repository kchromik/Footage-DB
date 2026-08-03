import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { AppSettings } from '../lib/types'

interface Props {
  notify: (message: string, kind?: 'ok' | 'error') => void
}

/** Dieselben Werte wie im Einrichtungsassistenten, nur später änderbar. */
export function SettingsPanel({ notify }: Props) {
  const [values, setValues] = useState<AppSettings | null>(null)
  const [password, setPassword] = useState('')
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open || values) return
    api
      .settings()
      .then(setValues)
      .catch((error) => notify((error as Error).message, 'error'))
  }, [open, values, notify])

  const save = async (patch: Record<string, unknown>) => {
    setBusy(true)
    try {
      setValues(await api.updateSettings(patch))
      notify('Gespeichert', 'ok')
    } catch (error) {
      notify((error as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card-block">
      <div
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
      >
        <h3 style={{ margin: 0 }}>Einstellungen</h3>
        <button className="btn ghost small" onClick={() => setOpen((value) => !value)}>
          {open ? 'Einklappen' : 'Anzeigen'}
        </button>
      </div>

      {open && !values && (
        <div style={{ display: 'grid', placeItems: 'center', padding: 24 }}>
          <span className="spinner" />
        </div>
      )}

      {open && values && (
        <div style={{ marginTop: 12 }}>
          <div className="form-row">
            <span className="label">Qualität der Previews</span>
            <div className="option-grid">
              {[
                { h: 540, crf: 28, title: 'Sparsam', desc: '540p' },
                { h: 720, crf: 26, title: 'Ausgewogen', desc: '720p' },
                { h: 1080, crf: 24, title: 'Scharf', desc: '1080p' },
              ].map((option) => (
                <button
                  key={option.h}
                  className={`option${values.proxy_height === option.h ? ' on' : ''}`}
                  disabled={busy}
                  onClick={() => save({ proxy_height: option.h, proxy_crf: option.crf })}
                >
                  <div className="title">{option.title}</div>
                  <div className="desc">{option.desc}</div>
                </button>
              ))}
            </div>
            <p className="note">
              Gilt für neu erzeugte Previews. Vorhandene bleiben, bis du einen Clip neu
              einlesen lässt.
            </p>
          </div>

          <div className="form-row">
            <span className="label">Gleichzeitige Aufgaben</span>
            <div className="range-row">
              <input
                type="range"
                min={1}
                max={8}
                value={values.worker_count}
                disabled={busy}
                onChange={(event) =>
                  setValues({ ...values, worker_count: Number(event.target.value) })
                }
                onMouseUp={() => save({ worker_count: values.worker_count })}
                onTouchEnd={() => save({ worker_count: values.worker_count })}
                style={{ flex: 1, accentColor: 'var(--text)' }}
              />
              <span className="mono" style={{ width: 18, textAlign: 'right' }}>
                {values.worker_count}
              </span>
            </div>
          </div>

          <div className="switch-row">
            <div className="text">
              <strong>Hardware-Encoding</strong>
              <span>
                Aktuell aktiv: {values.hwaccel_active === 'vaapi' ? 'Hardware (VAAPI)' : 'CPU'}
              </span>
            </div>
            <button
              className={`switch${values.hwaccel !== 'off' ? ' on' : ''}`}
              disabled={busy}
              onClick={() => save({ hwaccel: values.hwaccel === 'off' ? 'auto' : 'off' })}
            />
          </div>

          <div className="switch-row">
            <div className="text">
              <strong>Suche nach Bildinhalt</strong>
              <span>Neue Clips werden dann zusätzlich analysiert.</span>
            </div>
            <button
              className={`switch${values.semantic_enabled ? ' on' : ''}`}
              disabled={busy}
              onClick={() => save({ semantic_enabled: !values.semantic_enabled })}
            />
          </div>

          <div className="switch-row">
            <div className="text">
              <strong>Uploads einsortieren</strong>
              <span className="mono">{values.organize_pattern}</span>
            </div>
            <button
              className={`switch${values.organize_uploads ? ' on' : ''}`}
              disabled={busy}
              onClick={() => save({ organize_uploads: !values.organize_uploads })}
            />
          </div>

          <div className="switch-row">
            <div className="text">
              <strong>Regelmäßiger Rescan</strong>
              <span>
                {values.rescan_interval_minutes > 0
                  ? `alle ${values.rescan_interval_minutes} Minuten`
                  : 'aus'}
              </span>
            </div>
            <button
              className={`switch${values.rescan_interval_minutes > 0 ? ' on' : ''}`}
              disabled={busy}
              onClick={() =>
                save({
                  rescan_interval_minutes: values.rescan_interval_minutes > 0 ? 0 : 60,
                })
              }
            />
          </div>

          <div className="divider" />

          <div className="form-row" style={{ marginBottom: 0 }}>
            <span className="label">Passwort ändern</span>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                className="field"
                type="password"
                placeholder="Neues Passwort, mindestens 8 Zeichen"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <button
                className="btn"
                disabled={password.length < 8 || busy}
                onClick={async () => {
                  await save({ password })
                  setPassword('')
                }}
              >
                Setzen
              </button>
            </div>
            {values.password_from_env && (
              <p className="note">
                Aktuell kommt das Passwort aus der .env. Setzt du hier eines, gilt ab
                sofort dieses.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
