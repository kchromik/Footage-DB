import { useState } from 'react'
import type { Facets, Filters, Look } from '../lib/types'
import { CATEGORY_LABEL, CATEGORY_ORDER, LOOK_COLOR, LOOK_LABEL } from '../lib/format'
import { IconClose, IconFolder } from './Icons'

interface Props {
  facets: Facets | null
  filters: Filters
  onChange: (patch: Partial<Filters>) => void
  onReset: () => void
  collapsed: boolean
}

const FOLDER_PREVIEW = 10

export function FilterPanel({ facets, filters, onChange, onReset, collapsed }: Props) {
  const [allFolders, setAllFolders] = useState(false)

  const toggleTag = (name: string) => {
    onChange({
      tags: filters.tags.includes(name)
        ? filters.tags.filter((tag) => tag !== name)
        : [...filters.tags, name],
    })
  }

  const folders = facets?.folders ?? []
  const visibleFolders = allFolders ? folders : folders.slice(0, FOLDER_PREVIEW)
  const active =
    filters.tags.length > 0 ||
    !!filters.look ||
    !!filters.folder ||
    filters.favorite ||
    filters.only_missing ||
    !!filters.date_from ||
    !!filters.date_to ||
    !!filters.duration_min ||
    !!filters.duration_max

  return (
    <aside className={`panel${collapsed ? ' collapsed' : ''}`}>
      <div className="panel-head">
        <span className="label">Filter</span>
        {active && (
          <button className="btn ghost small" onClick={onReset}>
            <IconClose size={11} /> Zuruecksetzen
          </button>
        )}
      </div>

      <div className="panel-scroll">
        <div className="facet">
          <div className="facet-head">
            <span className="label">Schnellzugriff</span>
          </div>
          <div className="facet-list">
            <button
              className={`facet-item${filters.favorite ? ' on' : ''}`}
              onClick={() => onChange({ favorite: !filters.favorite })}
            >
              Favoriten
            </button>
            <button
              className={`facet-item${filters.only_missing ? ' on' : ''}`}
              onClick={() => onChange({ only_missing: !filters.only_missing })}
            >
              Fehlende Dateien
            </button>
          </div>
        </div>

        {facets && facets.looks.length > 0 && (
          <div className="facet">
            <div className="facet-head">
              <span className="label">Bildlook</span>
            </div>
            <div className="facet-list">
              {facets.looks.map((entry) => {
                const look = entry.name as Look
                return (
                  <button
                    key={entry.name}
                    className={`facet-item${filters.look === entry.name ? ' on' : ''}`}
                    onClick={() =>
                      onChange({ look: filters.look === entry.name ? '' : entry.name })
                    }
                  >
                    <i
                      className="swatch"
                      style={{ background: LOOK_COLOR[look] ?? 'var(--look-unknown)' }}
                    />
                    {LOOK_LABEL[look] ?? entry.name}
                    <span className="count">{entry.count}</span>
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {CATEGORY_ORDER.map((category) => {
          const entries = facets?.tags?.[category]
          if (!entries || entries.length === 0) return null
          return (
            <div className="facet" key={category}>
              <div className="facet-head">
                <span className="label">{CATEGORY_LABEL[category] ?? category}</span>
              </div>
              <div className="facet-list">
                {entries.map((entry) => (
                  <button
                    key={entry.name}
                    className={`facet-item${filters.tags.includes(entry.name) ? ' on' : ''}`}
                    onClick={() => toggleTag(entry.name)}
                  >
                    {entry.name}
                    <span className="count">{entry.count}</span>
                  </button>
                ))}
              </div>
            </div>
          )
        })}

        <div className="facet">
          <div className="facet-head">
            <span className="label">Aufnahmedatum</span>
          </div>
          <div className="range-row stack">
            <label>
              <span>von</span>
              <input
                type="date"
                className="field"
                value={filters.date_from}
                onChange={(event) => onChange({ date_from: event.target.value })}
              />
            </label>
            <label>
              <span>bis</span>
              <input
                type="date"
                className="field"
                value={filters.date_to}
                onChange={(event) => onChange({ date_to: event.target.value })}
              />
            </label>
          </div>
        </div>

        <div className="facet">
          <div className="facet-head">
            <span className="label">Laenge in Sekunden</span>
          </div>
          <div className="range-row">
            <input
              type="number"
              min={0}
              className="field"
              placeholder="ab"
              value={filters.duration_min}
              onChange={(event) => onChange({ duration_min: event.target.value })}
            />
            <span>bis</span>
            <input
              type="number"
              min={0}
              className="field"
              placeholder="bis"
              value={filters.duration_max}
              onChange={(event) => onChange({ duration_max: event.target.value })}
            />
          </div>
        </div>

        {folders.length > 0 && (
          <div className="facet">
            <div className="facet-head">
              <span className="label">Ordner</span>
            </div>
            <div className="facet-list" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
              {visibleFolders.map((entry) => {
                // Der Wurzelordner heisst in der Datenbank "", als Filterwert
                // steht dafuer "/", sonst waere er nicht von "kein Filter"
                // zu unterscheiden.
                const value = entry.name || '/'
                return (
                <button
                  key={value}
                  className={`facet-item${filters.folder === value ? ' on' : ''}`}
                  style={{ justifyContent: 'space-between' }}
                  onClick={() => onChange({ folder: filters.folder === value ? '' : value })}
                  title={entry.name || 'Wurzelordner'}
                >
                  <span
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    <IconFolder size={12} />
                    {entry.name || 'Wurzelordner'}
                  </span>
                  <span className="count">{entry.count}</span>
                </button>
                )
              })}
              {folders.length > FOLDER_PREVIEW && (
                <button
                  className="btn ghost small"
                  style={{ marginTop: 4, justifyContent: 'center' }}
                  onClick={() => setAllFolders((value) => !value)}
                >
                  {allFolders ? 'Weniger zeigen' : `Alle ${folders.length} zeigen`}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}
