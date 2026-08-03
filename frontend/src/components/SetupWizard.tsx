import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { MediaPreview, SetupStatus, SystemCheck } from '../lib/types'
import { IconArrowLeft, IconCheck, IconLogo } from './Icons'

interface Props {
  status: SetupStatus
  onDone: () => void
}

interface Draft {
  auth_user: string
  password: string
  password2: string
  proxy_height: number
  proxy_crf: number
  hwaccel: string
  semantic_enabled: boolean
  worker_count: number
  organize_uploads: boolean
  organize_pattern: string
  rescan_interval_minutes: number
  start_scan: boolean
}

const STEPS = [
  { id: 'willkommen', label: 'Willkommen' },
  { id: 'system', label: 'Systemprüfung' },
  { id: 'zugang', label: 'Zugang' },
  { id: 'bibliothek', label: 'Bibliothek' },
  { id: 'verarbeitung', label: 'Verarbeitung' },
  { id: 'ablage', label: 'Ablage' },
  { id: 'fertig', label: 'Fertig' },
] as const

const PATTERNS = [
  { value: '{year}/{year}-{month}/{camera}', title: 'Jahr / Monat / Kamera', desc: '2026/2026-07/Sony-FX3' },
  { value: '{year}/{year}-{month}', title: 'Jahr / Monat', desc: '2026/2026-07' },
  { value: '{camera}/{year}-{month}', title: 'Kamera / Jahr-Monat', desc: 'Sony-FX3/2026-07' },
]

function Switch({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className={`switch${on ? ' on' : ''}`}
      onClick={onClick}
      role="switch"
      aria-checked={on}
    />
  )
}

export function SetupWizard({ status, onDone }: Props) {
  const [step, setStep] = useState(0)
  const [check, setCheck] = useState<SystemCheck | null>(null)
  const [preview, setPreview] = useState<MediaPreview | null>(null)
  const [example, setExample] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const [draft, setDraft] = useState<Draft>({
    auth_user: status.auth_user || 'admin',
    password: '',
    password2: '',
    proxy_height: 720,
    proxy_crf: 26,
    hwaccel: 'auto',
    semantic_enabled: true,
    worker_count: 2,
    organize_uploads: true,
    organize_pattern: PATTERNS[0].value,
    rescan_interval_minutes: 60,
    start_scan: true,
  })

  const set = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }))
  const current = STEPS[step].id

  /* Der Zugangsschritt entfällt, wenn das Passwort schon in der .env steht */
  const skipZugang = status.password_from_env
  const visibleSteps = useMemo(
    () => STEPS.filter((entry) => entry.id !== 'zugang' || !skipZugang),
    [skipZugang],
  )

  useEffect(() => {
    if (current === 'system' && !check) {
      setBusy(true)
      api
        .systemCheck()
        .then((result) => {
          setCheck(result)
          // Vorschläge an die gefundene Hardware anpassen
          set({
            worker_count: Math.max(2, Math.min(4, Math.floor(result.cpu_count / 2))),
            hwaccel: result.hwaccel.available ? 'auto' : 'off',
            semantic_enabled: result.internet,
          })
        })
        .catch((issue) => setError((issue as Error).message))
        .finally(() => setBusy(false))
    }
    if (current === 'bibliothek' && !preview) {
      setBusy(true)
      api
        .mediaPreview()
        .then(setPreview)
        .catch((issue) => setError((issue as Error).message))
        .finally(() => setBusy(false))
    }
  }, [current, check, preview])

  useEffect(() => {
    if (current !== 'ablage') return
    api
      .patternPreview(draft.organize_pattern)
      .then((result) => setExample(result.example))
      .catch(() => setExample(''))
  }, [current, draft.organize_pattern])

  const passwordOk =
    skipZugang ||
    (draft.password.length >= 8 && draft.password === draft.password2)

  const canContinue = current === 'zugang' ? passwordOk : true

  const go = (direction: 1 | -1) => {
    setError('')
    let next = step + direction
    while (STEPS[next] && STEPS[next].id === 'zugang' && skipZugang) next += direction
    setStep(Math.max(0, Math.min(STEPS.length - 1, next)))
  }

  const finish = async () => {
    setBusy(true)
    setError('')
    try {
      await api.completeSetup({
        auth_user: draft.auth_user,
        password: skipZugang ? '' : draft.password,
        proxy_height: draft.proxy_height,
        proxy_crf: draft.proxy_crf,
        hwaccel: draft.hwaccel,
        semantic_enabled: draft.semantic_enabled,
        worker_count: draft.worker_count,
        organize_uploads: draft.organize_uploads,
        organize_pattern: draft.organize_pattern,
        rescan_interval_minutes: draft.rescan_interval_minutes,
        start_scan: draft.start_scan,
      })
      onDone()
    } catch (issue) {
      setError((issue as Error).message)
      setBusy(false)
    }
  }

  return (
    <div className="wizard-page">
      <div className="wizard">
        <nav className="wizard-rail">
          <div className="mark">
            <IconLogo size={19} />
          </div>
          <h2>FootageDB</h2>
          <p className="sub">Einrichtung</p>
          <div className="wizard-steps">
            {visibleSteps.map((entry) => {
              const index = STEPS.findIndex((s) => s.id === entry.id)
              const done = index < step
              return (
                <div
                  key={entry.id}
                  className={`wizard-step${done ? ' done' : ''}${
                    entry.id === current ? ' current' : ''
                  }`}
                >
                  <span className="num">
                    {done ? <IconCheck size={10} /> : visibleSteps.indexOf(entry) + 1}
                  </span>
                  {entry.label}
                </div>
              )
            })}
          </div>
        </nav>

        <div className="wizard-body">
          {current === 'willkommen' && (
            <>
              <header className="wizard-head">
                <h1>Willkommen bei FootageDB</h1>
                <p>
                  In wenigen Schritten ist deine B-Roll-Bibliothek eingerichtet. Wir
                  schauen kurz, ob alles bereit ist, legen deinen Zugang an und
                  klären, wie dein Material verarbeitet werden soll.
                </p>
              </header>
              <div className="wizard-content">
                <div className="switch-row">
                  <div className="text">
                    <strong>Dein Footage bleibt, wo es ist</strong>
                    <span>
                      FootageDB liest den Ordner {status.media_root} und legt dort nichts
                      ab. Vorschaubilder, Previews und die Datenbank landen getrennt davon
                      im Datenverzeichnis.
                    </span>
                  </div>
                </div>
                <div className="switch-row">
                  <div className="text">
                    <strong>Nichts wird verschoben, außer du sagst es</strong>
                    <span>
                      Das Einsortieren nach Jahr und Kamera ist ein eigener Schritt, den du
                      später startest. Er zeigt vorher jede geplante Bewegung und lässt
                      sich komplett rückgängig machen.
                    </span>
                  </div>
                </div>
                <div className="switch-row">
                  <div className="text">
                    <strong>Alles läuft lokal</strong>
                    <span>
                      Auch die Suche nach Bildinhalten. Dafür wird einmalig ein Modell
                      heruntergeladen, danach braucht FootageDB kein Internet mehr.
                    </span>
                  </div>
                </div>
              </div>
            </>
          )}

          {current === 'system' && (
            <>
              <header className="wizard-head">
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    justifyContent: 'space-between',
                    gap: 12,
                  }}
                >
                  <div>
                    <h1>Systemprüfung</h1>
                    <p>Ein kurzer Blick, ob alles vorhanden und erreichbar ist.</p>
                  </div>
                  <button
                    className="btn small"
                    disabled={busy}
                    onClick={() => {
                      setCheck(null)
                      setError('')
                    }}
                  >
                    Erneut prüfen
                  </button>
                </div>
              </header>
              <div className="wizard-content">
                {busy && !check ? (
                  <div style={{ display: 'grid', placeItems: 'center', padding: 40 }}>
                    <span className="spinner" />
                  </div>
                ) : check ? (
                  <>
                    <div
                      className={`check-row${check.media.exists ? (check.media.writable ? '' : ' warn') : ' bad'}`}
                    >
                      <i className="dot" />
                      <span className="name">Medienordner</span>
                      <span className="value">
                        {check.media.path}
                        <br />
                        {check.media.exists
                          ? `${check.media.writable ? 'lesbar und beschreibbar' : 'nur lesbar'}, ${check.media.free_label} frei von ${check.media.total_label}`
                          : 'nicht gefunden'}
                      </span>
                    </div>
                    <div className={`check-row${check.data.writable ? '' : ' bad'}`}>
                      <i className="dot" />
                      <span className="name">Datenverzeichnis</span>
                      <span className="value">
                        {check.data.path}
                        <br />
                        {check.data.writable ? 'beschreibbar' : 'nicht beschreibbar'},{' '}
                        {check.data.free_label} frei
                      </span>
                    </div>
                    <div
                      className={`check-row${check.media.writable ? '' : ' bad'}`}
                    >
                      <i className="dot" />
                      <span className="name">Rechte</span>
                      <span className="value">
                        Ordner gehört {check.permissions.media_uid}:
                        {check.permissions.media_gid}, Rechte {check.permissions.mode}
                        <br />
                        Container läuft als {check.permissions.container_uid}:
                        {check.permissions.container_gid}
                      </span>
                    </div>
                    <div className={`check-row${check.tools.ffmpeg ? '' : ' bad'}`}>
                      <i className="dot" />
                      <span className="name">ffmpeg</span>
                      <span className="value">{check.tools.ffmpeg ?? 'nicht gefunden'}</span>
                    </div>
                    <div className={`check-row${check.tools.exiftool ? '' : ' warn'}`}>
                      <i className="dot" />
                      <span className="name">exiftool</span>
                      <span className="value">
                        {check.tools.exiftool ?? 'nicht gefunden'}
                      </span>
                    </div>
                    <div className={`check-row${check.hwaccel.available ? '' : ' warn'}`}>
                      <i className="dot" />
                      <span className="name">Video-Encoding</span>
                      <span className="value">
                        {check.hwaccel.available
                          ? `Hardware über ${check.hwaccel.device}`
                          : check.hwaccel.device_present
                            ? 'Gerät da, aber nicht nutzbar, es wird die CPU verwendet'
                            : 'CPU (kein /dev/dri durchgereicht)'}
                        <br />
                        {check.cpu_count} CPU-Kerne
                      </span>
                    </div>
                    <div className={`check-row${check.internet ? '' : ' warn'}`}>
                      <i className="dot" />
                      <span className="name">Internet</span>
                      <span className="value">
                        {check.internet
                          ? 'erreichbar, das Suchmodell kann geladen werden'
                          : 'nicht erreichbar, die Bildinhaltssuche bleibt vorerst aus'}
                      </span>
                    </div>

                    {check.warnings.map((warning) => (
                      <div
                        className={`hint-box${check.ok ? '' : ' bad'}`}
                        key={warning}
                      >
                        <span className="bar" />
                        <span>{warning}</span>
                      </div>
                    ))}
                  </>
                ) : (
                  <div className="hint-box bad">
                    <span className="bar" />
                    <span>Die Prüfung ist fehlgeschlagen: {error}</span>
                  </div>
                )}
              </div>
            </>
          )}

          {current === 'zugang' && (
            <>
              <header className="wizard-head">
                <h1>Zugang einrichten</h1>
                <p>
                  Damit meldest du dich künftig an. Das Passwort wird nur als Hash
                  gespeichert, nicht im Klartext.
                </p>
              </header>
              <div className="wizard-content">
                <div className="form-row">
                  <span className="label">Benutzername</span>
                  <input
                    className="field"
                    value={draft.auth_user}
                    autoComplete="username"
                    onChange={(event) => set({ auth_user: event.target.value })}
                  />
                </div>
                <div className="form-row">
                  <span className="label">Passwort</span>
                  <input
                    className="field"
                    type="password"
                    value={draft.password}
                    autoComplete="new-password"
                    onChange={(event) => set({ password: event.target.value })}
                  />
                  <p className="note">Mindestens 8 Zeichen.</p>
                </div>
                <div className="form-row">
                  <span className="label">Passwort wiederholen</span>
                  <input
                    className="field"
                    type="password"
                    value={draft.password2}
                    autoComplete="new-password"
                    onChange={(event) => set({ password2: event.target.value })}
                  />
                  {draft.password2 && draft.password !== draft.password2 && (
                    <p className="note" style={{ color: 'var(--danger)' }}>
                      Die beiden Eingaben stimmen nicht überein.
                    </p>
                  )}
                </div>
              </div>
            </>
          )}

          {current === 'bibliothek' && (
            <>
              <header className="wizard-head">
                <h1>Deine Bibliothek</h1>
                <p>Das liegt gerade in {status.media_root}.</p>
              </header>
              <div className="wizard-content">
                {busy && !preview ? (
                  <div style={{ display: 'grid', placeItems: 'center', padding: 40 }}>
                    <span className="spinner" />
                  </div>
                ) : preview && preview.count > 0 ? (
                  <>
                    <div className="stat-inline">
                      <div>
                        <div className="value accent">
                          {preview.count.toLocaleString('de-DE')}
                          {preview.truncated && '+'}
                        </div>
                        <div className="name">Videodateien</div>
                      </div>
                      <div>
                        <div className="value">{preview.size_label}</div>
                        <div className="name">Speicher</div>
                      </div>
                      <div>
                        <div className="value">
                          {preview.estimate_minutes < 60
                            ? `${preview.estimate_minutes} min`
                            : `${Math.round(preview.estimate_minutes / 60)} h`}
                        </div>
                        <div className="name">Erste Verarbeitung</div>
                      </div>
                    </div>

                    {preview.folders.length > 0 && (
                      <>
                        <span className="label">Gefundene Ordner</span>
                        <div className="facet-list" style={{ marginTop: 8 }}>
                          {preview.folders.map((folder) => (
                            <span className="chip" key={folder.name}>
                              {folder.name}
                              <span style={{ color: 'var(--text-faint)' }}>
                                {folder.count}
                              </span>
                            </span>
                          ))}
                        </div>
                      </>
                    )}

                    <div className="hint-box">
                      <span className="bar" />
                      <span>
                        Die Schätzung ist eine grobe Hausnummer. Vorschaubilder sind
                        schnell da, die Previews brauchen den Großteil der Zeit. Du
                        kannst währenddessen schon suchen.
                      </span>
                    </div>
                  </>
                ) : (
                  <div className="hint-box">
                    <span className="bar" />
                    <span>
                      Im Medienordner liegt noch kein Videomaterial. Das ist kein Problem:
                      leg Dateien per NAS-Freigabe hinein oder lade sie später direkt in
                      der Oberfläche hoch.
                    </span>
                  </div>
                )}
              </div>
            </>
          )}

          {current === 'verarbeitung' && (
            <>
              <header className="wizard-head">
                <h1>Verarbeitung</h1>
                <p>
                  FootageDB erzeugt pro Clip ein kleines Preview, damit jedes Format im
                  Browser läuft. Diese Werte kannst du später jederzeit ändern.
                </p>
              </header>
              <div className="wizard-content">
                <div className="form-row">
                  <span className="label">Qualität der Previews</span>
                  <div className="option-grid">
                    {[
                      { h: 540, crf: 28, title: 'Sparsam', desc: '540p, wenig Platz und schnell' },
                      { h: 720, crf: 26, title: 'Ausgewogen', desc: '720p, gute Sicht auf Details' },
                      { h: 1080, crf: 24, title: 'Scharf', desc: '1080p, braucht deutlich mehr Zeit' },
                    ].map((option) => (
                      <button
                        key={option.h}
                        className={`option${draft.proxy_height === option.h ? ' on' : ''}`}
                        onClick={() => set({ proxy_height: option.h, proxy_crf: option.crf })}
                      >
                        <div className="title">{option.title}</div>
                        <div className="desc">{option.desc}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="form-row">
                  <span className="label">Gleichzeitige Aufgaben</span>
                  <div className="range-row">
                    <input
                      type="range"
                      min={1}
                      max={Math.max(4, check?.cpu_count ?? 4)}
                      value={draft.worker_count}
                      onChange={(event) =>
                        set({ worker_count: Number(event.target.value) })
                      }
                      style={{ flex: 1, accentColor: 'var(--text)' }}
                    />
                    <span className="mono" style={{ width: 18, textAlign: 'right' }}>
                      {draft.worker_count}
                    </span>
                  </div>
                  <p className="note">
                    Mehr geht schneller, belastet das NAS aber stärker. Bei{' '}
                    {check?.cpu_count ?? '?'} Kernen sind 2 bis 4 ein guter Wert.
                  </p>
                </div>

                <div className="divider" />

                <div className="switch-row">
                  <div className="text">
                    <strong>Hardware-Encoding nutzen</strong>
                    <span>
                      {check?.hwaccel.available
                        ? 'Die iGPU ist nutzbar, das beschleunigt die Previews deutlich.'
                        : 'Auf diesem System nicht verfügbar, es wird die CPU verwendet.'}
                    </span>
                  </div>
                  <Switch
                    on={draft.hwaccel !== 'off'}
                    onClick={() => set({ hwaccel: draft.hwaccel === 'off' ? 'auto' : 'off' })}
                  />
                </div>

                <div className="switch-row">
                  <div className="text">
                    <strong>Suche nach Bildinhalt</strong>
                    <span>
                      Findet Clips über eine Beschreibung wie "Sonnenuntergang am Wasser".
                      Lädt einmalig rund 600 MB und rechnet pro Clip ein paar Sekunden
                      mehr.
                      {check && !check.internet && ' Aktuell ist kein Internet erreichbar.'}
                    </span>
                  </div>
                  <Switch
                    on={draft.semantic_enabled}
                    onClick={() => set({ semantic_enabled: !draft.semantic_enabled })}
                  />
                </div>

                <div className="switch-row">
                  <div className="text">
                    <strong>Regelmäßig nach neuen Dateien schauen</strong>
                    <span>
                      Zusätzlich zur Live-Überwachung des Ordners, stündlich. Sinnvoll
                      bei Netzlaufwerken, wo Änderungen nicht immer gemeldet werden.
                    </span>
                  </div>
                  <Switch
                    on={draft.rescan_interval_minutes > 0}
                    onClick={() =>
                      set({
                        rescan_interval_minutes: draft.rescan_interval_minutes > 0 ? 0 : 60,
                      })
                    }
                  />
                </div>
              </div>
            </>
          )}

          {current === 'ablage' && (
            <>
              <header className="wizard-head">
                <h1>Ablage neuer Dateien</h1>
                <p>
                  Wohin sollen Dateien wandern, die du über die Oberfläche hochlädst?
                </p>
              </header>
              <div className="wizard-content">
                <div className="switch-row">
                  <div className="text">
                    <strong>Uploads automatisch einsortieren</strong>
                    <span>
                      Ist das aus, landen neue Dateien direkt im Wurzelordner deiner
                      Bibliothek.
                    </span>
                  </div>
                  <Switch
                    on={draft.organize_uploads}
                    onClick={() => set({ organize_uploads: !draft.organize_uploads })}
                  />
                </div>

                {draft.organize_uploads && (
                  <div className="form-row" style={{ marginTop: 16 }}>
                    <span className="label">Ordnerschema</span>
                    <div className="option-grid">
                      {PATTERNS.map((option) => (
                        <button
                          key={option.value}
                          className={`option${draft.organize_pattern === option.value ? ' on' : ''}`}
                          onClick={() => set({ organize_pattern: option.value })}
                        >
                          <div className="title">{option.title}</div>
                          <div className="desc mono">{option.desc}</div>
                        </button>
                      ))}
                    </div>
                    {example && (
                      <p className="note">
                        Beispiel: <span className="mono">{example}</span>
                      </p>
                    )}
                  </div>
                )}

                <div className="hint-box">
                  <span className="bar" />
                  <span>
                    Dein vorhandener Bestand bleibt unangetastet. Wenn du ihn später
                    ebenfalls in dieses Schema bringen willst, findest du das unter
                    Werkzeuge, mit Vorschau und Rückwärtsgang.
                  </span>
                </div>
              </div>
            </>
          )}

          {current === 'fertig' && (
            <>
              <header className="wizard-head">
                <h1>Alles bereit</h1>
                <p>Ein letzter Blick, danach geht es los.</p>
              </header>
              <div className="wizard-content">
                <dl className="summary-grid">
                  <dt>Benutzer</dt>
                  <dd>{draft.auth_user}</dd>
                  <dt>Passwort</dt>
                  <dd>
                    {skipZugang ? 'kommt aus der .env' : 'gesetzt'}
                  </dd>
                  <dt>Medienordner</dt>
                  <dd>{status.media_root}</dd>
                  <dt>Gefunden</dt>
                  <dd>
                    {preview ? `${preview.count} Dateien, ${preview.size_label}` : 'nicht geprüft'}
                  </dd>
                  <dt>Previews</dt>
                  <dd>
                    {draft.proxy_height}p, CRF {draft.proxy_crf}
                  </dd>
                  <dt>Encoding</dt>
                  <dd>
                    {draft.hwaccel === 'off'
                      ? 'CPU'
                      : check?.hwaccel.available
                        ? 'Hardware (VAAPI)'
                        : 'automatisch, aktuell CPU'}
                  </dd>
                  <dt>Gleichzeitig</dt>
                  <dd>{draft.worker_count} Aufgaben</dd>
                  <dt>Bildinhaltssuche</dt>
                  <dd>{draft.semantic_enabled ? 'an' : 'aus'}</dd>
                  <dt>Uploads</dt>
                  <dd>
                    {draft.organize_uploads
                      ? (example ||
                        PATTERNS.find((entry) => entry.value === draft.organize_pattern)?.desc ||
                        draft.organize_pattern)
                      : 'in den Wurzelordner'}
                  </dd>
                </dl>

                <div className="divider" />

                <div className="switch-row">
                  <div className="text">
                    <strong>Bibliothek jetzt einlesen</strong>
                    <span>
                      Startet direkt nach dem Abschließen. Du kannst währenddessen schon
                      stöbern, die Kacheln füllen sich nach und nach.
                    </span>
                  </div>
                  <Switch
                    on={draft.start_scan}
                    onClick={() => set({ start_scan: !draft.start_scan })}
                  />
                </div>

                {error && (
                  <div className="hint-box bad">
                    <span className="bar" />
                    <span>{error}</span>
                  </div>
                )}
              </div>
            </>
          )}

          <footer className="wizard-foot">
            <button
              className="btn ghost"
              onClick={() => go(-1)}
              disabled={step === 0 || busy}
            >
              <IconArrowLeft size={13} /> Zurück
            </button>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="mono" style={{ fontSize: 11, color: 'var(--text-faint)' }}>
                {visibleSteps.findIndex((entry) => entry.id === current) + 1} von{' '}
                {visibleSteps.length}
              </span>
              {current === 'fertig' ? (
                <button className="btn primary" onClick={finish} disabled={busy}>
                  {busy ? <span className="spinner" /> : 'Einrichtung abschließen'}
                </button>
              ) : (
                <button
                  className="btn primary"
                  onClick={() => go(1)}
                  disabled={!canContinue || busy}
                >
                  Weiter
                </button>
              )}
            </div>
          </footer>
        </div>
      </div>
    </div>
  )
}
