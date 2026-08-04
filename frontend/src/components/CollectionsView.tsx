import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Collection } from '../lib/types'
import { formatDate } from '../lib/format'
import { IconCollection, IconEdit, IconFilm, IconPlus, IconTrash } from './Icons'

interface Props {
  notify: (message: string, kind?: 'ok' | 'error') => void
  onOpen: (collection: Collection) => void
  /** Zähler hochzählen, um die Liste neu zu laden */
  refreshKey: number
}

export function CollectionsView({ notify, onOpen, refreshKey }: Props) {
  const [items, setItems] = useState<Collection[] | null>(null)
  const [draft, setDraft] = useState('')
  const [renaming, setRenaming] = useState<number | null>(null)
  const [renameDraft, setRenameDraft] = useState('')

  const load = async () => {
    try {
      setItems((await api.collections()).items)
    } catch (error) {
      notify(`Sammlungen konnten nicht geladen werden: ${(error as Error).message}`, 'error')
      setItems([])
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  const create = async () => {
    const name = draft.trim()
    if (!name) return
    try {
      await api.createCollection(name)
      setDraft('')
      notify(`Sammlung "${name}" angelegt`, 'ok')
      await load()
    } catch (error) {
      notify((error as Error).message, 'error')
    }
  }

  const rename = async (collection: Collection) => {
    const name = renameDraft.trim()
    setRenaming(null)
    if (!name || name === collection.name) return
    try {
      await api.renameCollection(collection.id, name)
      await load()
    } catch (error) {
      notify((error as Error).message, 'error')
    }
  }

  return (
    <div className="view">
      <div className="view-head">
        <h2>Sammlungen</h2>
        <p>
          Clips für ein Projekt zusammenstellen. Ein Clip darf in beliebig vielen
          Sammlungen liegen, auf der Festplatte wird nichts verschoben oder kopiert.
        </p>
      </div>

      <div className="card-block">
        <h3>Neue Sammlung</h3>
        <div className="collection-new">
          <input
            className="field"
            placeholder="Name, zum Beispiel Reise Japan oder Intro 2026"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void create()
            }}
          />
          <button className="btn primary" onClick={() => void create()} disabled={!draft.trim()}>
            <IconPlus size={13} /> Anlegen
          </button>
        </div>
      </div>

      {items === null ? (
        <div className="empty">
          <div className="spinner" />
        </div>
      ) : items.length === 0 ? (
        <div className="empty">
          <IconCollection size={40} />
          <h3>Noch keine Sammlung</h3>
          <p>
            Leg oben eine an. Danach kannst du in der Bibliothek Clips markieren und
            über die Auswahlleiste hineinlegen.
          </p>
        </div>
      ) : (
        <div className="collection-grid">
          {items.map((collection) => (
            <article
              className="collection-card"
              key={collection.id}
              onClick={() => onOpen(collection)}
            >
              <div className="collection-cover">
                {collection.cover_url ? (
                  <img src={collection.cover_url} alt="" loading="lazy" decoding="async" />
                ) : (
                  <div className="placeholder">
                    <IconFilm size={26} />
                  </div>
                )}
                <span className="badge">{collection.count}</span>
              </div>
              <div className="collection-body">
                {renaming === collection.id ? (
                  <input
                    className="field"
                    autoFocus
                    value={renameDraft}
                    onClick={(event) => event.stopPropagation()}
                    onChange={(event) => setRenameDraft(event.target.value)}
                    onBlur={() => void rename(collection)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') void rename(collection)
                      if (event.key === 'Escape') setRenaming(null)
                    }}
                  />
                ) : (
                  <div className="collection-name" title={collection.name}>
                    {collection.name}
                  </div>
                )}
                <div className="collection-meta">
                  {collection.count === 1 ? '1 Clip' : `${collection.count} Clips`}
                  <i className="dot" />
                  {formatDate(collection.created_at)}
                </div>
              </div>
              <div className="collection-actions">
                <button
                  className="btn ghost small"
                  aria-label="Umbenennen"
                  onClick={(event) => {
                    event.stopPropagation()
                    setRenameDraft(collection.name)
                    setRenaming(collection.id)
                  }}
                >
                  <IconEdit size={12} />
                </button>
                <button
                  className="btn ghost small"
                  aria-label="Löschen"
                  onClick={async (event) => {
                    event.stopPropagation()
                    if (
                      !window.confirm(
                        `Sammlung "${collection.name}" löschen? Die Clips selbst bleiben.`,
                      )
                    )
                      return
                    await api.deleteCollection(collection.id)
                    notify('Sammlung gelöscht')
                    await load()
                  }}
                >
                  <IconTrash size={12} />
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
