import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { ActiveJob, ProgressInfo } from '../lib/types'
import { useEvents } from '../lib/useEvents'
import { IconClose, IconFilm, IconRefresh } from './Icons'

interface Props {
  notify: (message: string, kind?: 'ok' | 'error') => void
}

/** Sekunden knapp und lesbar: erst Sekunden, dann Minuten, dann Stunden. */
function kurz(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  if (total < 60) return `${total} s`
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  if (minutes < 60) return `${minutes}:${String(rest).padStart(2, '0')} min`
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')} h`
}

function prozent(fraction: number | null): string {
  if (fraction === null) return ''
  return `${Math.floor(fraction * 100)} %`
}

/** Eine laufende Aufgabe mit Balken, Tempo und Restzeit. */
function JobRow({ job }: { job: ActiveJob }) {
  const details = [
    job.stage,
    job.speed ? `${job.speed.toFixed(1)}x` : '',
    job.fps ? `${Math.round(job.fps)} fps` : '',
    `läuft ${kurz(job.elapsed)}`,
    job.eta !== null ? `noch etwa ${kurz(job.eta)}` : '',
  ].filter(Boolean)

  return (
    <div className="job-row">
      <div className="job-head">
        <span className="job-label">{job.label}</span>
        <span className="job-file mono" title={`${job.folder ? `${job.folder}/` : ''}${job.filename}`}>
          {job.filename || 'ohne Datei'}
        </span>
        <span className="job-percent mono">{prozent(job.fraction)}</span>
      </div>
      <div className={`job-track${job.fraction === null ? ' unknown' : ''}`}>
        <div
          className="job-fill"
          style={job.fraction === null ? undefined : { width: `${job.fraction * 100}%` }}
        />
      </div>
      <div className="job-detail">{details.join(' · ')}</div>
    </div>
  )
}

/**
 * Zeigt, woran die Hintergrundarbeit gerade sitzt.
 *
 * Die laufenden Aufgaben kommen als Ereignis herein, sobald sich etwas
 * bewegt. Alles Übrige (Warteschlange, Fehler, zuletzt Fertiges) wird
 * daneben regelmäßig geholt, das ändert sich langsam genug.
 */
export function ProgressPanel({ notify }: Props) {
  const [info, setInfo] = useState<ProgressInfo | null>(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef<number>()

  const load = useCallback(async () => {
    try {
      setInfo(await api.progress())
    } catch {
      /* Nicht kritisch, der nächste Durchlauf versucht es erneut */
    }
  }, [])

  useEffect(() => {
    void load()
    const interval = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(interval)
  }, [load])

  /* Der Fortschritt einer einzelnen Datei kommt live, die Zahlen daneben
     erst beim nächsten Abruf. Ein Ereignis stößt ihn zusätzlich an, damit
     eine leer gewordene Warteschlange nicht fünf Sekunden nachhängt. */
  useEvents(
    useCallback(
      (event) => {
        if (event.type === 'progress') {
          const items = (event.items ?? []) as ActiveJob[]
          setInfo((current) => (current ? { ...current, active: items } : current))
          if (items.length === 0) {
            window.clearTimeout(timer.current)
            timer.current = window.setTimeout(() => void load(), 600)
          }
        }
        if (event.type === 'scan') void load()
      },
      [load],
    ),
    true,
  )

  const retry = async () => {
    setBusy(true)
    try {
      const result = await api.retryJobs()
      notify(`${result.requeued} Aufgaben erneut eingereiht`, 'ok')
      await load()
    } catch (error) {
      notify((error as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  if (!info) {
    return (
      <div className="card-block">
        <h3>Was gerade läuft</h3>
        <div style={{ display: 'grid', placeItems: 'center', padding: 24 }}>
          <span className="spinner" />
        </div>
      </div>
    )
  }

  const wartend = info.by_type.filter((entry) => entry.queued > 0)
  /* Was insgesamt noch aussteht. Die Warteschlange kennt nur die Jobs, die
     schon angelegt sind, und die entstehen erst Clip für Clip. */
  const offen = (
    [
      ['Vorschaubilder', info.pending.poster],
      ['Vorschauen', info.pending.proxy],
      ['Vorschaustreifen', info.pending.sprite],
      ['Bildanalysen', info.pending.embed],
    ] as [string, number][]
  ).filter(([, count]) => count > 0)
  const scanAnteil =
    info.scan.total > 0 ? Math.min(1, info.scan.done / info.scan.total) : null

  return (
    <div className="card-block">
      <div className="block-head">
        <h3>Was gerade läuft</h3>
        <span className="block-meta mono">
          {info.worker_count} {info.worker_count === 1 ? 'Aufgabe' : 'Aufgaben'} parallel
          {' · '}
          {info.acceleration === 'vaapi' ? 'Hardware (VAAPI)' : 'CPU'}
        </span>
      </div>

      {info.scanning && (
        <div className="job-row">
          <div className="job-head">
            <span className="job-label">Medienordner einlesen</span>
            <span className="job-file mono">
              {info.scan.total > 0
                ? `${info.scan.done.toLocaleString('de-DE')} von ${info.scan.total.toLocaleString('de-DE')} Dateien`
                : 'Dateien werden gesucht'}
            </span>
            <span className="job-percent mono">{prozent(scanAnteil)}</span>
          </div>
          <div className={`job-track${scanAnteil === null ? ' unknown' : ''}`}>
            <div
              className="job-fill"
              style={scanAnteil === null ? undefined : { width: `${scanAnteil * 100}%` }}
            />
          </div>
        </div>
      )}

      {info.active.map((job) => (
        <JobRow key={job.job_id} job={job} />
      ))}

      {!info.scanning && info.active.length === 0 && (
        <div className="job-idle">
          <IconFilm size={15} />
          <span>
            Gerade ist nichts in Arbeit.
            {info.queue.queued > 0
              ? ` ${info.queue.queued} Aufgaben stehen an und werden gleich geholt.`
              : ' Alles ist durchgerechnet.'}
          </span>
        </div>
      )}

      <div className="queue-line">
        <span className="mono">
          Warteschlange: {info.queue.queued.toLocaleString('de-DE')} offen,{' '}
          {info.queue.running} in Arbeit
        </span>
        {wartend.map((entry) => (
          <span className="queue-chip" key={entry.type}>
            {entry.label}
            <b className="mono">{entry.queued.toLocaleString('de-DE')}</b>
          </span>
        ))}
        {info.done_last_10min > 0 && (
          <span className="mono" style={{ color: 'var(--text-faint)' }}>
            {info.done_last_10min} in den letzten 10 Minuten fertig
          </span>
        )}
      </div>

      {offen.length > 0 && (
        <div className="queue-line" style={{ borderTop: 'none', paddingTop: 4 }}>
          <span className="mono">Insgesamt offen:</span>
          {offen.map(([label, count]) => (
            <span className="queue-chip" key={label}>
              {label}
              <b className="mono">{count.toLocaleString('de-DE')}</b>
            </span>
          ))}
        </div>
      )}

      {info.recent.length > 0 && (
        <div className="recent-list">
          <div className="label">Zuletzt fertig</div>
          {info.recent.map((entry, index) => (
            <div className="recent-row" key={`${entry.finished_at}-${index}`}>
              <span className="what">{entry.label}</span>
              <span className="file mono">{entry.filename || 'ohne Datei'}</span>
              <span className="took mono">{kurz(entry.seconds)}</span>
            </div>
          ))}
        </div>
      )}

      {info.failed.length > 0 && (
        <div className="failed-list">
          <div className="failed-head">
            <span className="label" style={{ color: 'var(--danger)' }}>
              {info.queue.failed} fehlgeschlagen
            </span>
            <button className="btn ghost small" disabled={busy} onClick={() => void retry()}>
              <IconRefresh size={12} /> Alle wiederholen
            </button>
          </div>
          {info.failed.map((entry) => (
            <div className="failed-row" key={entry.id}>
              <span className="what">
                <IconClose size={10} /> {entry.label}
              </span>
              <span className="file mono">{entry.filename || 'ohne Datei'}</span>
              <span className="why mono" title={entry.error ?? ''}>
                {entry.error ?? 'Grund unbekannt'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
