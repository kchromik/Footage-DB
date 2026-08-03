import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { MoveBatch, MovePlan, Stats } from '../lib/types'
import { formatDate } from '../lib/format'
import { IconRefresh } from './Icons'
import { SettingsPanel } from './SettingsPanel'

interface Props {
  stats: Stats | null
  notify: (message: string, kind?: 'ok' | 'error') => void
  onLibraryChanged: () => void
}

export function ToolsView({ stats, notify, onLibraryChanged }: Props) {
  const [plan, setPlan] = useState<MovePlan | null>(null)
  const [batches, setBatches] = useState<MoveBatch[]>([])
  const [busy, setBusy] = useState<string | null>(null)

  const loadBatches = async () => {
    try {
      setBatches((await api.batches()).items)
    } catch {
      /* nicht kritisch */
    }
  }

  useEffect(() => {
    void loadBatches()
  }, [])

  const run = async (name: string, action: () => Promise<void>) => {
    setBusy(name)
    try {
      await action()
    } catch (error) {
      notify((error as Error).message, 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="view">
      <div className="view-head">
        <h2>Werkzeuge</h2>
        <p>Bibliothek einlesen, Dateien einsortieren und aufräumen.</p>
      </div>

      <SettingsPanel notify={notify} />

      <div className="card-block">
        <h3>Bibliothek einlesen</h3>
        <p style={{ margin: '0 0 12px', color: 'var(--text-dim)', fontSize: 12.5 }}>
          Sucht neue und geänderte Dateien im Medienordner. Läuft außerdem
          automatisch, sobald sich dort etwas tut.
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            className="btn primary"
            disabled={stats?.scanning || busy === 'scan'}
            onClick={() =>
              run('scan', async () => {
                const result = await api.scan()
                notify(result.started ? 'Scan gestartet' : (result.detail ?? 'Läuft bereits'))
              })
            }
          >
            <IconRefresh size={14} />
            {stats?.scanning ? 'Scan läuft' : 'Jetzt scannen'}
          </button>
          {(stats?.queue.failed ?? 0) > 0 && (
            <button
              className="btn"
              onClick={() =>
                run('retry', async () => {
                  const result = await api.retryJobs()
                  notify(`${result.requeued} Aufgaben erneut eingereiht`)
                })
              }
            >
              {stats?.queue.failed} fehlgeschlagene Aufgaben wiederholen
            </button>
          )}
        </div>
        {stats && (
          <div className="mono" style={{ marginTop: 12, fontSize: 11, color: 'var(--text-faint)' }}>
            Warteschlange: {stats.queue.queued} offen, {stats.queue.running} in Arbeit
            {stats.pending.proxy > 0 && `, ${stats.pending.proxy} Vorschauen ausstehend`}
            {stats.pending.embed > 0 && `, ${stats.pending.embed} Bildanalysen ausstehend`}
          </div>
        )}
      </div>

      <div className="card-block">
        <h3>Dateien einsortieren</h3>
        <p style={{ margin: '0 0 12px', color: 'var(--text-dim)', fontSize: 12.5 }}>
          Verschiebt vorhandene Dateien in das Schema{' '}
          <code className="mono" style={{ color: 'var(--text)' }}>
            {plan?.pattern ?? '{year}/{year}-{month}/{camera}'}
          </code>
          . Erst planen, danach ausführen. Jeder Durchgang lässt sich rückgängig machen.
        </p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            className="btn"
            disabled={busy === 'plan'}
            onClick={() =>
              run('plan', async () => {
                const result = await api.planOrganize()
                setPlan(result)
                notify(
                  result.count === 0
                    ? 'Alles liegt schon richtig'
                    : `${result.count} Dateien würden verschoben`,
                )
              })
            }
          >
            Plan erstellen
          </button>
          {plan && plan.count > 0 && (
            <button
              className="btn primary"
              disabled={busy === 'apply'}
              onClick={() => {
                if (!window.confirm(`${plan.count} Dateien wirklich verschieben?`)) return
                void run('apply', async () => {
                  const result = await api.applyOrganize()
                  notify(`${result.moved} Dateien verschoben`, 'ok')
                  setPlan(null)
                  await loadBatches()
                  onLibraryChanged()
                })
              }}
            >
              {plan.count} Dateien verschieben
            </button>
          )}
        </div>

        {plan && (
          <div style={{ marginTop: 14 }}>
            <div className="mono" style={{ fontSize: 11, color: 'var(--text-faint)', marginBottom: 8 }}>
              {plan.count} zu verschieben, {plan.already_sorted} bereits richtig
              {plan.skipped.length > 0 && `, ${plan.skipped.length} übersprungen`}
              {plan.truncated && ' (Vorschau gekürzt)'}
            </div>
            {plan.preview.length > 0 && (
              <div className="scroll-box">
                <table className="move-table">
                  <thead>
                    <tr>
                      <th>Von</th>
                      <th>Nach</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.preview.map((move) => (
                      <tr key={move.clip_id}>
                        <td>{move.from}</td>
                        <td className="to">{move.to}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {batches.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div className="label" style={{ marginBottom: 8 }}>
              Bisherige Durchgänge
            </div>
            {batches.map((batch) => (
              <div
                key={batch.batch}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 10,
                  padding: '6px 0',
                  borderBottom: '1px solid var(--line)',
                  fontSize: 12,
                }}
              >
                <span className="mono" style={{ color: 'var(--text-dim)' }}>
                  {formatDate(batch.created_at, true)} - {batch.done} verschoben
                  {batch.reverted > 0 && `, ${batch.reverted} zurückgenommen`}
                </span>
                {batch.done > 0 && (
                  <button
                    className="btn ghost small"
                    onClick={() => {
                      if (!window.confirm('Diesen Durchgang rückgängig machen?')) return
                      void run('undo', async () => {
                        const result = await api.undoBatch(batch.batch)
                        notify(`${result.reverted} Dateien zurückgelegt`, 'ok')
                        await loadBatches()
                        onLibraryChanged()
                      })
                    }}
                  >
                    Rückgängig
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card-block">
        <h3>Aufräumen</h3>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            className="btn"
            onClick={() =>
              run('cleanup', async () => {
                const result = await api.cleanup()
                notify(
                  `${result.removed_artifacts} verwaiste Vorschaudateien und ${result.removed_tags} ungenutzte Tags entfernt`,
                  'ok',
                )
              })
            }
          >
            Verwaiste Vorschauen entfernen
          </button>
          {(stats?.missing ?? 0) > 0 && (
            <button
              className="btn danger"
              onClick={() => {
                if (!window.confirm(`${stats?.missing} fehlende Einträge aus der Datenbank entfernen?`))
                  return
                void run('purge', async () => {
                  const result = await api.purgeMissing()
                  notify(`${result.removed} Einträge entfernt`, 'ok')
                  onLibraryChanged()
                })
              }}
            >
              {stats?.missing} fehlende Einträge entfernen
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
