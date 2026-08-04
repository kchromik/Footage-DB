import { useEffect, useMemo, useState } from 'react'
import type { Clip } from '../lib/types'
import { TagPicker } from './TagPicker'
import { IconClose, IconTag } from './Icons'

interface Props {
  clips: Clip[]
  onClose: () => void
  onApply: (add: string[], remove: string[]) => Promise<void>
}

/** Tags, die von Hand vergeben wurden, mit Anzahl der betroffenen Clips. */
function manualTagCounts(clips: Clip[]): { name: string; count: number }[] {
  const counts = new Map<string, number>()
  clips.forEach((clip) => {
    clip.tags
      .filter((tag) => tag.source === 'manual')
      .forEach((tag) => counts.set(tag.name, (counts.get(tag.name) ?? 0) + 1))
  })
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'de'))
}

export function BatchTagDialog({ clips, onClose, onApply }: Props) {
  const [add, setAdd] = useState<string[]>([])
  const [remove, setRemove] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const vorhanden = useMemo(() => manualTagCounts(clips), [clips])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [onClose])

  const apply = async () => {
    if (add.length === 0 && remove.length === 0) return
    setBusy(true)
    try {
      await onApply(add, remove)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="overlay"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="dialog" role="dialog" aria-label="Tags für die Auswahl">
        <div className="dialog-head">
          <div>
            <h3>
              <IconTag size={14} /> Tags für {clips.length}{' '}
              {clips.length === 1 ? 'Clip' : 'Clips'}
            </h3>
            <p>Automatisch vergebene Tags bleiben unangetastet.</p>
          </div>
          <button className="round-btn" onClick={onClose} aria-label="Schließen">
            <IconClose size={14} />
          </button>
        </div>

        <div className="dialog-body">
          <div className="label" style={{ marginBottom: 8 }}>
            Hinzufügen
          </div>
          <TagPicker value={add} onChange={setAdd} placeholder="Tag suchen oder anlegen" />

          {vorhanden.length > 0 && (
            <>
              <div className="label" style={{ margin: '18px 0 8px' }}>
                Entfernen
              </div>
              <div className="tag-editor">
                {vorhanden.map((tag) => {
                  const markiert = remove.includes(tag.name)
                  return (
                    <button
                      key={tag.name}
                      className={`tag-pill toggle${markiert ? ' danger' : ''}`}
                      onClick={() =>
                        setRemove((current) =>
                          markiert
                            ? current.filter((name) => name !== tag.name)
                            : [...current, tag.name],
                        )
                      }
                      title={
                        tag.count === clips.length
                          ? 'Auf allen ausgewählten Clips'
                          : `Auf ${tag.count} von ${clips.length} Clips`
                      }
                    >
                      {tag.name}
                      <span className="count">{tag.count}</span>
                    </button>
                  )
                })}
              </div>
              {remove.length > 0 && (
                <div className="dialog-hint">
                  {remove.length === 1 ? 'Ein Tag wird' : `${remove.length} Tags werden`} von
                  der Auswahl entfernt.
                </div>
              )}
            </>
          )}
        </div>

        <div className="dialog-actions">
          <button className="btn ghost" onClick={onClose}>
            Abbrechen
          </button>
          <button
            className="btn primary"
            disabled={busy || (add.length === 0 && remove.length === 0)}
            onClick={() => void apply()}
          >
            {busy ? 'wird gespeichert' : 'Übernehmen'}
          </button>
        </div>
      </div>
    </div>
  )
}
