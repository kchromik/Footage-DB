import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { CATEGORY_LABEL } from '../lib/format'
import { IconClose } from './Icons'

interface Suggestion {
  name: string
  category: string
  count: number
}

interface Props {
  value: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
  /** Zaehler hochzaehlen, um die Vorschlaege neu zu laden */
  refreshKey?: number
}

const QUICK_PICKS = 8

export function TagPicker({ value, onChange, placeholder, refreshKey = 0 }: Props) {
  const [draft, setDraft] = useState('')
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const [known, setKnown] = useState<Suggestion[]>([])
  const boxRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api
      .tags()
      .then((result) =>
        setKnown(
          result.items
            .filter((tag) => tag.count > 0)
            .map((tag) => ({
              name: tag.name,
              category: tag.category,
              count: tag.count,
            })),
        ),
      )
      .catch(() => undefined)
  }, [refreshKey])

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const chosen = useMemo(
    () => new Set(value.map((tag) => tag.toLowerCase())),
    [value],
  )

  const matches = useMemo(() => {
    const needle = draft.trim().toLowerCase()
    const frei = known.filter((tag) => !chosen.has(tag.name.toLowerCase()))
    if (!needle) return frei.slice(0, QUICK_PICKS)
    return frei
      .filter((tag) => tag.name.toLowerCase().includes(needle))
      .sort((a, b) => {
        // Treffer am Wortanfang zuerst
        const aStart = a.name.toLowerCase().startsWith(needle) ? 0 : 1
        const bStart = b.name.toLowerCase().startsWith(needle) ? 0 : 1
        return aStart - bStart || b.count - a.count
      })
      .slice(0, 10)
  }, [draft, known, chosen])

  const trimmed = draft.trim()
  const kannAnlegen =
    trimmed.length > 0 &&
    !chosen.has(trimmed.toLowerCase()) &&
    !known.some((tag) => tag.name.toLowerCase() === trimmed.toLowerCase())

  const optionen = kannAnlegen ? [...matches, null] : matches

  const add = (name: string) => {
    const clean = name.trim()
    if (!clean || chosen.has(clean.toLowerCase())) return
    onChange([...value, clean])
    setDraft('')
    setHighlight(0)
    inputRef.current?.focus()
  }

  const remove = (name: string) => {
    onChange(value.filter((tag) => tag !== name))
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      setHighlight((index) => Math.min(index + 1, optionen.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlight((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const gewaehlt = optionen[highlight]
      if (gewaehlt) add(gewaehlt.name)
      else if (kannAnlegen) add(trimmed)
    } else if (event.key === 'Escape') {
      setOpen(false)
    } else if (event.key === 'Backspace' && !draft && value.length > 0) {
      remove(value[value.length - 1])
    } else if (event.key === ',' || event.key === 'Tab') {
      if (trimmed) {
        event.preventDefault()
        add(trimmed)
      }
    }
  }

  return (
    <div className="tag-picker" ref={boxRef}>
      <div
        className={`tag-picker-field${open ? ' open' : ''}`}
        onClick={() => {
          inputRef.current?.focus()
          setOpen(true)
        }}
      >
        {value.map((tag) => (
          <span className="tag-pill" key={tag}>
            {tag}
            <button
              onClick={(event) => {
                event.stopPropagation()
                remove(tag)
              }}
              aria-label={`${tag} entfernen`}
            >
              <IconClose size={10} />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          value={draft}
          placeholder={value.length === 0 ? (placeholder ?? 'Tag suchen oder anlegen') : ''}
          onChange={(event) => {
            setDraft(event.target.value)
            setOpen(true)
            setHighlight(0)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
      </div>

      {open && optionen.length > 0 && (
        <div className="tag-suggestions">
          {!draft && matches.length > 0 && (
            <div className="tag-suggestion-head">Haeufig verwendet</div>
          )}
          {optionen.map((option, index) =>
            option ? (
              <button
                key={option.name}
                className={`tag-suggestion${index === highlight ? ' on' : ''}`}
                onMouseEnter={() => setHighlight(index)}
                onClick={() => add(option.name)}
              >
                <span>{option.name}</span>
                <span className="meta">
                  {CATEGORY_LABEL[option.category] ?? option.category} · {option.count}
                </span>
              </button>
            ) : (
              <button
                key="__neu"
                className={`tag-suggestion neu${index === highlight ? ' on' : ''}`}
                onMouseEnter={() => setHighlight(index)}
                onClick={() => add(trimmed)}
              >
                <span>„{trimmed}" anlegen</span>
                <span className="meta">neues Tag</span>
              </button>
            ),
          )}
        </div>
      )}
    </div>
  )
}
