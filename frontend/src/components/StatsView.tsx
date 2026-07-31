import type { Stats } from '../lib/types'
import { LOOK_COLOR, LOOK_LABEL, formatDate, formatLongDuration } from '../lib/format'
import type { Look } from '../lib/types'

interface Props {
  stats: Stats | null
}

function Bars({
  title,
  rows,
}: {
  title: string
  rows: { name: string; count: number }[]
}) {
  if (rows.length === 0) return null
  const max = Math.max(...rows.map((row) => row.count), 1)
  return (
    <div className="card-block">
      <h3>{title}</h3>
      {rows.map((row) => (
        <div className="bar-row" key={row.name}>
          <span className="name" title={row.name}>
            {row.name}
          </span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(row.count / max) * 100}%` }} />
          </div>
          <span className="num">{row.count}</span>
        </div>
      ))}
    </div>
  )
}

export function StatsView({ stats }: Props) {
  if (!stats) {
    return (
      <div className="view">
        <div className="empty">
          <div className="spinner" />
        </div>
      </div>
    )
  }

  return (
    <div className="view">
      <div className="view-head">
        <h2>Bibliothek</h2>
        <p>Ein Überblick, was in deinem Footage-Ordner steckt.</p>
      </div>

      <div className="stat-grid">
        <div className="stat">
          <div className="value accent">{stats.clips.toLocaleString('de-DE')}</div>
          <div className="name">Clips</div>
        </div>
        <div className="stat">
          <div className="value">{formatLongDuration(stats.seconds)}</div>
          <div className="name">Gesamtlänge</div>
        </div>
        <div className="stat">
          <div className="value">{stats.size_label}</div>
          <div className="name">Speicher</div>
        </div>
        <div className="stat">
          <div className="value">{stats.by_camera.length}</div>
          <div className="name">Kameras</div>
        </div>
      </div>

      <Bars
        title="Nach Kamera"
        rows={stats.by_camera.map((row) => ({ name: row.name, count: row.count }))}
      />
      <Bars
        title="Nach Jahr"
        rows={stats.by_year.map((row) => ({ name: row.year || 'unbekannt', count: row.count }))}
      />
      <Bars title="Technische Merkmale" rows={stats.by_resolution} />

      <div className="card-block">
        <h3>Bildlook</h3>
        {stats.by_look.map((row) => (
          <div className="bar-row" key={row.name}>
            <span className="name" style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <i
                style={{
                  width: 7,
                  height: 7,
                  borderRadius: '50%',
                  background: LOOK_COLOR[row.name as Look] ?? 'var(--look-unknown)',
                }}
              />
              {LOOK_LABEL[row.name as Look] ?? row.name}
            </span>
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{
                  width: `${(row.count / Math.max(...stats.by_look.map((r) => r.count), 1)) * 100}%`,
                  background: LOOK_COLOR[row.name as Look] ?? undefined,
                  opacity: 0.85,
                }}
              />
            </div>
            <span className="num">{row.count}</span>
          </div>
        ))}
      </div>

      <div className="card-block">
        <h3>System</h3>
        <dl className="spec-grid" style={{ gridTemplateColumns: '160px 1fr' }}>
          <dt>Medienordner</dt>
          <dd>{stats.media_root}</dd>
          <dt>Letzter Scan</dt>
          <dd>{stats.last_scan_at ? formatDate(stats.last_scan_at, true) : 'noch keiner'}</dd>
          <dt>Video-Encoding</dt>
          <dd>{stats.acceleration === 'vaapi' ? 'Hardware (VAAPI)' : 'CPU'}</dd>
          <dt>Inhaltliche Suche</dt>
          <dd>
            {stats.semantic.enabled
              ? `${stats.semantic.model_status}, ${stats.semantic.indexed} Clips erfasst`
              : 'ausgeschaltet'}
          </dd>
          <dt>Offene Aufgaben</dt>
          <dd>
            {stats.queue.queued + stats.queue.running} in Arbeit
            {stats.queue.failed > 0 ? `, ${stats.queue.failed} fehlgeschlagen` : ''}
          </dd>
          {stats.missing > 0 && (
            <>
              <dt>Fehlende Dateien</dt>
              <dd style={{ color: 'var(--danger)' }}>{stats.missing}</dd>
            </>
          )}
        </dl>
      </div>
    </div>
  )
}
