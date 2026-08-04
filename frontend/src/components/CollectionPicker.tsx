import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { Collection } from '../lib/types'
import { IconCheck, IconCollection, IconPlus } from './Icons'

interface Props {
  clipIds: number[]
  /** IDs der Sammlungen, in denen der Clip schon liegt (nur bei einem Clip) */
  memberOf?: number[]
  onClose: () => void
  onChanged: (message: string) => void
  /** Nach oben aufklappen, wenn der Auslöser unten am Rand sitzt */
  drop?: 'up' | 'down'
}

export function CollectionPicker({
  clipIds,
  memberOf = [],
  onClose,
  onChanged,
  drop = 'up',
}: Props) {
  const [items, setItems] = useState<Collection[] | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api
      .collections()
      .then((result) => setItems(result.items))
      .catch(() => setItems([]))
  }, [])

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) onClose()
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey, true)
    }
  }, [onClose])

  const needle = draft.trim().toLowerCase()
  const matches = useMemo(
    () => (items ?? []).filter((entry) => entry.name.toLowerCase().includes(needle)),
    [items, needle],
  )
  const kannAnlegen =
    draft.trim().length > 0 &&
    !(items ?? []).some((entry) => entry.name.toLowerCase() === needle)

  const single = clipIds.length === 1
  const label = single ? 'Clip' : `${clipIds.length} Clips`

  const toggle = async (collection: Collection) => {
    if (busy) return
    setBusy(true)
    try {
      if (single && memberOf.includes(collection.id)) {
        await api.removeFromCollection(collection.id, clipIds)
        onChanged(`Aus "${collection.name}" entfernt`)
      } else {
        const result = await api.addToCollection(collection.id, clipIds)
        onChanged(
          result.added === 0
            ? `Liegt schon in "${collection.name}"`
            : `${result.added === 1 ? '1 Clip' : `${result.added} Clips`} in "${collection.name}"`,
        )
      }
      onClose()
    } finally {
      setBusy(false)
    }
  }

  const create = async () => {
    const name = draft.trim()
    if (!name || busy) return
    setBusy(true)
    try {
      const collection = await api.createCollection(name)
      await api.addToCollection(collection.id, clipIds)
      onChanged(`${label} in neuer Sammlung "${name}"`)
      onClose()
    } catch (error) {
      onChanged((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`collection-picker ${drop}`} ref={boxRef}>
      <div className="collection-picker-head">
        {single ? 'Clip in Sammlung legen' : `${clipIds.length} Clips in Sammlung legen`}
      </div>
      <input
        className="field"
        autoFocus
        placeholder="Suchen oder neu anlegen"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== 'Enter') return
          if (matches.length === 1) void toggle(matches[0])
          else if (kannAnlegen) void create()
        }}
      />
      <div className="collection-picker-list">
        {items === null && <div className="collection-picker-empty">lädt</div>}
        {items !== null && matches.length === 0 && !kannAnlegen && (
          <div className="collection-picker-empty">Noch keine Sammlung angelegt</div>
        )}
        {matches.map((collection) => {
          const drin = memberOf.includes(collection.id)
          return (
            <button
              key={collection.id}
              className={`collection-picker-item${drin ? ' on' : ''}`}
              disabled={busy}
              onClick={() => void toggle(collection)}
              title={drin && single ? 'Aus der Sammlung nehmen' : 'Hineinlegen'}
            >
              <IconCollection size={13} />
              <span className="name">{collection.name}</span>
              {drin ? <IconCheck size={12} /> : <span className="count">{collection.count}</span>}
            </button>
          )
        })}
        {kannAnlegen && (
          <button className="collection-picker-item neu" disabled={busy} onClick={() => void create()}>
            <IconPlus size={13} />
            <span className="name">„{draft.trim()}" anlegen</span>
          </button>
        )}
      </div>
    </div>
  )
}
