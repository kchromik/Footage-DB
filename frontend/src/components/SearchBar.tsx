import { useCallback, useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { api } from '../lib/api'
import type { Filters, SuggestItem } from '../lib/types'
import { LOOK_COLOR } from '../lib/format'
import type { Look } from '../lib/types'
import {
  IconCollection,
  IconFilm,
  IconFolder,
  IconSearch,
  IconStar,
  IconTag,
} from './Icons'

interface Props {
  value: string
  onValueChange: (value: string) => void
  mode: Filters['mode']
  onModeChange: (mode: Filters['mode']) => void
  /** Bereits gesetzte Tags, damit ein Vorschlag nicht doppelt angeboten wird */
  activeTags: string[]
  onPick: (item: SuggestItem) => void
  inputRef: RefObject<HTMLInputElement>
}

const MODES: [Filters['mode'], string, string][] = [
  ['auto', 'Auto', 'Kombiniert beide Verfahren'],
  ['text', 'Text', 'Sucht in Dateinamen, Tags und Metadaten'],
  ['semantic', 'Inhalt', 'Sucht nach dem, was im Bild zu sehen ist'],
]

function KindIcon({ item }: { item: SuggestItem }) {
  switch (item.kind) {
    case 'folder':
      return <IconFolder size={12} />
    case 'clip':
      return <IconFilm size={12} />
    case 'collection':
      return <IconCollection size={12} />
    case 'quick':
      return <IconStar size={12} />
    case 'look':
      return (
        <i
          className="swatch"
          style={{ background: LOOK_COLOR[item.value as Look] ?? 'var(--look-unknown)' }}
        />
      )
    default:
      return <IconTag size={12} />
  }
}

/** Hebt die getippte Stelle im Vorschlag hervor. */
function Highlight({ text, query }: { text: string; query: string }) {
  const needle = query.trim().toLowerCase()
  const position = needle ? text.toLowerCase().indexOf(needle) : -1
  if (position < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, position)}
      <mark>{text.slice(position, position + needle.length)}</mark>
      {text.slice(position + needle.length)}
    </>
  )
}

/**
 * Suchfeld mit Vorschlägen.
 *
 * Vorgeschlagen wird nicht der Treffer, sondern der Filter dorthin: Tags
 * jeder Art (Kamera, Objektiv, Technik, eigene), Ordner, Bildlook,
 * Sammlungen und der Schnellzugriff, dazu Dateinamen zum direkten Öffnen.
 * Solange die Bildinhalte nicht durchsuchbar sind, führen die Tags am
 * schnellsten ans Ziel, deshalb stehen sie oben.
 */
export function SearchBar({
  value,
  onValueChange,
  mode,
  onModeChange,
  activeTags,
  onPick,
  inputRef,
}: Props) {
  const [items, setItems] = useState<SuggestItem[]>([])
  const [open, setOpen] = useState(false)
  const [cursor, setCursor] = useState(-1)
  const listRef = useRef<HTMLDivElement>(null)
  const abort = useRef<AbortController>()

  /* Vorschläge holen, verzögert und immer nur die jüngste Anfrage */
  useEffect(() => {
    const text = value.trim()
    if (text.length < 1) {
      setItems([])
      setCursor(-1)
      return
    }
    const timer = window.setTimeout(async () => {
      abort.current?.abort()
      const controller = new AbortController()
      abort.current = controller
      try {
        const result = await api.suggest(text, controller.signal)
        setItems(result.items.filter((item) => !(item.kind === 'tag' && activeTags.includes(item.value))))
        setCursor(-1)
      } catch {
        /* Abgebrochen oder offline: dann eben keine Vorschläge */
      }
    }, 160)
    return () => window.clearTimeout(timer)
  }, [value, activeTags])

  useEffect(() => {
    if (cursor < 0) return
    listRef.current?.querySelector(`[data-index="${cursor}"]`)?.scrollIntoView({
      block: 'nearest',
    })
  }, [cursor])

  const pick = useCallback(
    (item: SuggestItem) => {
      setOpen(false)
      setItems([])
      setCursor(-1)
      onPick(item)
    },
    [onPick],
  )

  const sichtbar = open && items.length > 0

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (!sichtbar) {
      if (event.key === 'ArrowDown' && items.length > 0) {
        event.preventDefault()
        setOpen(true)
        setCursor(0)
      }
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setCursor((index) => (index + 1) % items.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setCursor((index) => (index <= 0 ? items.length - 1 : index - 1))
    } else if (event.key === 'Enter') {
      if (cursor >= 0 && items[cursor]) {
        event.preventDefault()
        pick(items[cursor])
      } else {
        setOpen(false)
      }
    } else if (event.key === 'Escape') {
      // Nicht ans Fenster weiterreichen, sonst verlässt der Fokus das Feld,
      // obwohl nur die Liste zugeklappt werden sollte.
      event.stopPropagation()
      event.preventDefault()
      setOpen(false)
    } else if (event.key === 'Tab') {
      setOpen(false)
    }
  }

  let letzteGruppe = ''

  return (
    <div className="search">
      <span className="icon">
        <IconSearch />
      </span>
      <input
        ref={inputRef}
        value={value}
        placeholder="Suchen: Tag, Kamera, Objektiv, Ordner, Dateiname oder Bildinhalt"
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => {
          onValueChange(event.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      <div className="modes">
        {MODES.map(([key, label, title]) => (
          <button
            key={key}
            className={mode === key ? 'on' : ''}
            onClick={() => onModeChange(key)}
            title={title}
          >
            {label}
          </button>
        ))}
      </div>

      {sichtbar && (
        <div className="search-suggest" ref={listRef}>
          {items.map((item, index) => {
            const kopf = item.group !== letzteGruppe ? item.group : null
            letzteGruppe = item.group
            return (
              <div key={`${item.kind}-${item.value}-${index}`}>
                {kopf && <div className="suggest-head">{kopf}</div>}
                <button
                  data-index={index}
                  className={`suggest-item${cursor === index ? ' on' : ''}`}
                  // Ohne das nimmt der Klick dem Feld den Fokus, die Liste
                  // klappt zu und der Klick landet im Leeren.
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setCursor(index)}
                  onClick={() => pick(item)}
                >
                  <span className="kind">
                    <KindIcon item={item} />
                  </span>
                  <span className="name">
                    <Highlight text={item.label} query={value} />
                  </span>
                  {item.detail && <span className="detail mono">{item.detail}</span>}
                  {item.count > 0 && <span className="count mono">{item.count}</span>}
                </button>
              </div>
            )
          })}
          <div className="suggest-foot">
            <span>
              <b>Enter</b> übernimmt, <b>Pfeiltasten</b> wählen aus
            </span>
            <span>weiter tippen sucht im Text</span>
          </div>
        </div>
      )}
    </div>
  )
}
