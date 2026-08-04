import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from './lib/api'
import { EMPTY_FILTERS } from './lib/types'
import type { Clip, Collection, Facets, Filters, SetupStatus, Stats } from './lib/types'
import { useEvents } from './lib/useEvents'
import { LOOK_LABEL } from './lib/format'
import type { Look } from './lib/types'
import { BatchTagDialog } from './components/BatchTagDialog'
import { ClipCard } from './components/ClipCard'
import { ClipDetail } from './components/ClipDetail'
import { CollectionPicker } from './components/CollectionPicker'
import { CollectionsView } from './components/CollectionsView'
import { FilterPanel } from './components/FilterPanel'
import { Login } from './components/Login'
import { SetupWizard } from './components/SetupWizard'
import { ShortcutsHelp } from './components/ShortcutsHelp'
import { StatsView } from './components/StatsView'
import { ToolsView } from './components/ToolsView'
import { UploadView } from './components/UploadView'
import { Toasts, useToasts } from './components/Toasts'
import { ThemeToggle } from './components/ThemeToggle'
import {
  IconCheck,
  IconClose,
  IconCollection,
  IconDownload,
  IconFilm,
  IconFilter,
  IconKeyboard,
  IconLibrary,
  IconLogo,
  IconLogout,
  IconSearch,
  IconSimilar,
  IconStar,
  IconStats,
  IconTag,
  IconTools,
  IconUpload,
} from './components/Icons'

type View = 'library' | 'collections' | 'upload' | 'stats' | 'tools'
type Phase = 'prüfen' | 'anmelden' | 'wizard' | 'bereit'

const PAGE_SIZE = 60
const SIMILAR_SIZE = 60

const SORT_OPTIONS: [string, string][] = [
  ['recorded_desc', 'Aufnahme, neueste zuerst'],
  ['recorded_asc', 'Aufnahme, älteste zuerst'],
  ['added_desc', 'Zuletzt hinzugefügt'],
  ['duration_desc', 'Länge, absteigend'],
  ['duration_asc', 'Länge, aufsteigend'],
  ['size_desc', 'Dateigröße'],
  ['name_asc', 'Dateiname'],
]

export default function App() {
  const [phase, setPhase] = useState<Phase>('prüfen')
  const [setupStatus, setSetupStatus] = useState<SetupStatus | null>(null)
  const [view, setView] = useState<View>('library')
  const [panelOpen, setPanelOpen] = useState(true)
  const [dense, setDense] = useState(false)

  const [filters, setFilters] = useState<Filters>(() => {
    const params = new URLSearchParams(window.location.search)
    return { ...EMPTY_FILTERS, q: params.get('q') ?? '' }
  })
  const [searchDraft, setSearchDraft] = useState(filters.q)

  const [items, setItems] = useState<Clip[]>([])
  const [facets, setFacets] = useState<Facets | null>(null)
  const [total, setTotal] = useState(0)
  const [mode, setMode] = useState('filter')
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [freshCount, setFreshCount] = useState(0)

  const [selection, setSelection] = useState<number[]>([])
  const [cursor, setCursor] = useState(-1)
  const [detail, setDetail] = useState<Clip | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)

  /* Ähnlichkeitssuche: ersetzt vorübergehend die normale Trefferliste */
  const [similarTo, setSimilarTo] = useState<Clip | null>(null)
  const [similarStatus, setSimilarStatus] = useState('')

  const [activeCollection, setActiveCollection] = useState<Collection | null>(null)
  const [collectionsKey, setCollectionsKey] = useState(0)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [tagDialogOpen, setTagDialogOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)

  const { toasts, notify } = useToasts()
  const searchRef = useRef<HTMLInputElement>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  const lastToggled = useRef<number | null>(null)
  const sentinel = useRef<HTMLDivElement>(null)
  const pendingRefresh = useRef<Set<number>>(new Set())

  /* ------------------------------------------------------------ Anmeldung */

  /* Zuerst klären, ob die Einrichtung schon durch ist. Vor dem Assistenten
     gibt es je nach Konfiguration noch gar kein Passwort. */
  const bootstrap = useCallback(async () => {
    try {
      const status = await api.setupStatus()
      setSetupStatus(status)
      if (!status.complete) {
        setPhase(status.has_password && !status.logged_in ? 'anmelden' : 'wizard')
        return
      }
      const info = await api.me()
      setPhase(info.user ? 'bereit' : 'anmelden')
    } catch {
      setPhase('anmelden')
    }
  }, [])

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  /* ------------------------------------------------------------ Suchfeld */

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setFilters((current) => (current.q === searchDraft ? current : { ...current, q: searchDraft }))
    }, 260)
    return () => window.clearTimeout(timer)
  }, [searchDraft])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (filters.q) params.set('q', filters.q)
    else params.delete('q')
    const search = params.toString()
    window.history.replaceState(null, '', search ? `?${search}` : window.location.pathname)
  }, [filters.q])

  /* Der Name der Sammlung hängt am Filter, nicht umgekehrt */
  useEffect(() => {
    if (!filters.collection) setActiveCollection(null)
  }, [filters.collection])

  /* -------------------------------------------------------------- Laden */

  const loadPage = useCallback(
    async (offset: number, replace: boolean) => {
      if (replace) setLoading(true)
      else setLoadingMore(true)
      try {
        const page = await api.clips(filters, offset, PAGE_SIZE, replace)
        setTotal(page.total)
        setMode(page.mode)
        if (page.facets) setFacets(page.facets)
        setItems((current) => (replace ? page.items : [...current, ...page.items]))
        if (replace) {
          setFreshCount(0)
          setCursor(-1)
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          setPhase('anmelden')
        } else {
          notify(`Laden fehlgeschlagen: ${(error as Error).message}`, 'error')
        }
      } finally {
        setLoading(false)
        setLoadingMore(false)
      }
    },
    [filters, notify],
  )

  const loadSimilar = useCallback(
    async (clip: Clip) => {
      setLoading(true)
      try {
        const page = await api.similar(clip.id, SIMILAR_SIZE)
        setItems(page.items)
        setTotal(page.items.length)
        setMode('similar')
        setSimilarStatus(page.status)
        setSelection([])
        setCursor(page.items.length > 0 ? 0 : -1)
      } catch (error) {
        notify(`Ähnliche Clips: ${(error as Error).message}`, 'error')
      } finally {
        setLoading(false)
      }
    },
    [notify],
  )

  useEffect(() => {
    if (phase !== 'bereit') return
    if (similarTo) {
      void loadSimilar(similarTo)
      return
    }
    void loadPage(0, true)
  }, [phase, similarTo, loadSimilar, loadPage])

  const refreshStats = useCallback(() => {
    api
      .stats()
      .then(setStats)
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (phase !== 'bereit') return
    refreshStats()
    const timer = window.setInterval(refreshStats, 20000)
    return () => window.clearInterval(timer)
  }, [phase, refreshStats])

  /* Unendliches Nachladen beim Scrollen, aber nicht in der Ähnlichkeitssuche */
  useEffect(() => {
    const node = sentinel.current
    if (!node || view !== 'library' || similarTo) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (
          entries[0].isIntersecting &&
          !loading &&
          !loadingMore &&
          items.length < total
        ) {
          void loadPage(items.length, false)
        }
      },
      { rootMargin: '600px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [items.length, total, loading, loadingMore, loadPage, view, similarTo])

  /* ---------------------------------------------------------- Ereignisse */

  const applyPending = useCallback(async () => {
    const ids = Array.from(pendingRefresh.current)
    pendingRefresh.current.clear()
    if (ids.length === 0) return
    const known = new Set(items.map((clip) => clip.id))
    const toFetch = ids.filter((id) => known.has(id)).slice(0, 24)
    const fresh = ids.filter((id) => !known.has(id)).length
    if (fresh > 0) setFreshCount((count) => count + fresh)
    if (toFetch.length === 0) return
    const updated = await Promise.all(
      toFetch.map((id) => api.clip(id).catch(() => null)),
    )
    setItems((current) =>
      current.map((clip) => updated.find((entry) => entry?.id === clip.id) ?? clip),
    )
  }, [items])

  const pendingTimer = useRef<number>()
  useEvents(
    useCallback(
      (event) => {
        if (event.type === 'queue' || event.type === 'scan') {
          if (event.type === 'scan' && event.state === 'done') refreshStats()
          setStats((current) =>
            current
              ? {
                  ...current,
                  scanning: event.type === 'scan' ? event.state !== 'done' : current.scanning,
                  queue:
                    event.type === 'queue'
                      ? {
                          queued: Number(event.queued ?? 0),
                          running: Number(event.running ?? 0),
                          failed: Number(event.failed ?? 0),
                        }
                      : current.queue,
                }
              : current,
          )
          return
        }
        if (event.type === 'clip' && typeof event.id === 'number') {
          pendingRefresh.current.add(event.id)
          window.clearTimeout(pendingTimer.current)
          pendingTimer.current = window.setTimeout(() => void applyPending(), 1500)
        }
      },
      [applyPending, refreshStats],
    ),
    phase === 'bereit',
  )

  /* ------------------------------------------------------------ Auswahl */

  const toggleSelection = useCallback(
    (clip: Clip, shiftKey: boolean) => {
      setSelection((current) => {
        if (shiftKey && lastToggled.current !== null) {
          const ids = items.map((entry) => entry.id)
          const from = ids.indexOf(lastToggled.current)
          const to = ids.indexOf(clip.id)
          if (from !== -1 && to !== -1) {
            const range = ids.slice(Math.min(from, to), Math.max(from, to) + 1)
            return Array.from(new Set([...current, ...range]))
          }
        }
        lastToggled.current = clip.id
        return current.includes(clip.id)
          ? current.filter((id) => id !== clip.id)
          : [...current, clip.id]
      })
    },
    [items],
  )

  /* -------------------------------------------------------------- Detail */

  const openDetail = useCallback(async (clip: Clip) => {
    setDetail(clip)
    try {
      setDetail(await api.clip(clip.id))
    } catch {
      /* Kurzfassung reicht auch */
    }
  }, [])

  const navigateDetail = useCallback(
    (direction: -1 | 1) => {
      if (!detail) return
      const index = items.findIndex((clip) => clip.id === detail.id)
      const next = items[index + direction]
      if (next) {
        setCursor(index + direction)
        void openDetail(next)
      }
    },
    [detail, items, openDetail],
  )

  const patchClipInList = useCallback((clip: Clip) => {
    setItems((current) => current.map((entry) => (entry.id === clip.id ? clip : entry)))
    setDetail((current) => (current && current.id === clip.id ? clip : current))
  }, [])

  const refreshClips = useCallback(
    async (ids: number[]) => {
      // Bei kleinen Stapeln reicht es, die betroffenen Clips nachzuladen,
      // sonst springt die Ansicht durch ein komplettes Neuladen.
      if (ids.length > 24) {
        if (similarTo) void loadSimilar(similarTo)
        else void loadPage(0, true)
        return
      }
      const fresh = await Promise.all(ids.map((id) => api.clip(id).catch(() => null)))
      setItems((current) =>
        current.map((clip) => fresh.find((entry) => entry?.id === clip.id) ?? clip),
      )
    },
    [loadPage, loadSimilar, similarTo],
  )

  /* ------------------------------------------------------------ Ableitung */

  const changeFilters = useCallback((patch: Partial<Filters>) => {
    setSimilarTo(null)
    setFilters((current) => {
      const next = { ...current, ...patch }
      // Die Sortierung nach Sammlungsreihenfolge gibt es außerhalb einer
      // Sammlung nicht, sonst stünde im Auswahlfeld nichts Passendes
      if (!next.collection && next.sort === 'collection_pos') {
        next.sort = EMPTY_FILTERS.sort
      }
      return next
    })
    setSelection([])
  }, [])

  const openCollection = useCallback((collection: Collection) => {
    setSimilarTo(null)
    setActiveCollection(collection)
    setSelection([])
    setFilters({ ...EMPTY_FILTERS, collection: collection.id, sort: 'collection_pos' })
    setSearchDraft('')
    setView('library')
  }, [])

  const showSimilar = useCallback((clip: Clip) => {
    setDetail(null)
    setView('library')
    setSimilarTo(clip)
  }, [])

  /* Ziel der Stapelaktionen: die Markierung, sonst der Clip unter dem Cursor */
  const targetIds = useMemo(() => {
    if (selection.length > 0) return selection
    return cursor >= 0 && items[cursor] ? [items[cursor].id] : []
  }, [selection, cursor, items])

  const targetClips = useMemo(
    () => items.filter((clip) => targetIds.includes(clip.id)),
    [items, targetIds],
  )

  const applyBatchTags = useCallback(
    async (add: string[], remove: string[]) => {
      try {
        await api.batchTags({ clip_ids: targetIds, add, remove })
        setTagDialogOpen(false)
        const teile = [
          add.length > 0 ? `${add.length} vergeben` : '',
          remove.length > 0 ? `${remove.length} entfernt` : '',
        ].filter(Boolean)
        notify(`Tags: ${teile.join(', ')}`, 'ok')
        await refreshClips(targetIds)
      } catch (error) {
        notify(`Tags konnten nicht gesetzt werden: ${(error as Error).message}`, 'error')
      }
    },
    [targetIds, notify, refreshClips],
  )

  const toggleFavorite = useCallback(
    async (clip: Clip) => {
      try {
        patchClipInList(await api.updateClip(clip.id, { favorite: !clip.favorite }))
      } catch (error) {
        notify((error as Error).message, 'error')
      }
    },
    [patchClipInList, notify],
  )

  /* -------------------------------------------------------- Tastatur */

  const columnCount = useCallback(() => {
    const cards = Array.from(gridRef.current?.children ?? []) as HTMLElement[]
    if (cards.length === 0) return 1
    // Wie viele Kacheln teilen sich die oberste Reihe? Das Raster ist
    // fließend, deshalb wird die Spaltenzahl aus dem Layout abgelesen.
    const top = cards[0].offsetTop
    let columns = 0
    for (const card of cards) {
      if (card.offsetTop !== top) break
      columns += 1
    }
    return Math.max(1, columns)
  }, [])

  const moveCursor = useCallback(
    (delta: number) => {
      setCursor((current) => {
        if (items.length === 0) return -1
        if (current < 0) return 0
        return Math.min(items.length - 1, Math.max(0, current + delta))
      })
    },
    [items.length],
  )

  /* Nur bei einer Cursorbewegung nachführen. Hinge das auch an der Anzahl
     der Clips, würde jedes Nachladen beim Scrollen zurück zum Cursor
     springen. */
  useEffect(() => {
    if (cursor < 0) return
    const node = gridRef.current?.querySelector(`[data-clip-index="${cursor}"]`)
    node?.scrollIntoView({ block: 'nearest' })
  }, [cursor])

  /* Ohne Markierung gibt es keinen Auswahlbalken, der die Sammlungsauswahl
     tragen könnte */
  useEffect(() => {
    if (selection.length === 0) setPickerOpen(false)
  }, [selection.length])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target
      const typing =
        target instanceof HTMLElement &&
        (['INPUT', 'TEXTAREA'].includes(target.tagName) || target.isContentEditable)

      if (event.key === '?' && !typing) {
        event.preventDefault()
        setHelpOpen((open) => !open)
        return
      }
      if (event.key === '/' && !typing) {
        event.preventDefault()
        setView('library')
        searchRef.current?.focus()
        return
      }
      if (typing) {
        if (event.key === 'Escape') (target as HTMLElement).blur()
        return
      }
      // Detailansicht, Dialoge und Modifikatoren haben Vorrang
      if (detail || tagDialogOpen || helpOpen || pickerOpen) return
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (view !== 'library') return

      // Auf einem fokussierten Knopf lösen Leertaste und Enter den Knopf aus,
      // das darf nicht zusätzlich den Clip unter dem Cursor treffen
      const aufKnopf =
        target instanceof HTMLElement && ['BUTTON', 'A', 'SELECT'].includes(target.tagName)
      if (aufKnopf && [' ', 'Enter'].includes(event.key)) return

      const current = cursor >= 0 ? items[cursor] : undefined

      switch (event.key) {
        case 'j':
        case 'ArrowRight':
          event.preventDefault()
          moveCursor(1)
          break
        case 'k':
        case 'ArrowLeft':
          event.preventDefault()
          moveCursor(-1)
          break
        case 'ArrowDown':
          event.preventDefault()
          moveCursor(columnCount())
          break
        case 'ArrowUp':
          event.preventDefault()
          moveCursor(-columnCount())
          break
        case 'Enter':
          if (current) void openDetail(current)
          break
        case ' ':
        case 'x':
          event.preventDefault()
          if (current) toggleSelection(current, event.shiftKey)
          break
        case 'a':
          event.preventDefault()
          setSelection(items.map((clip) => clip.id))
          break
        case 'f':
          if (current) void toggleFavorite(current)
          break
        case 't':
          if (targetIds.length > 0) setTagDialogOpen(true)
          break
        case 'c':
          // Der Auswahlbalken trägt den Sammlungs-Knopf, also erst markieren
          if (selection.length === 0 && current) setSelection([current.id])
          if (targetIds.length > 0) setPickerOpen(true)
          break
        case 's':
          if (current) showSimilar(current)
          break
        case 'Escape':
          if (selection.length > 0) setSelection([])
          else if (similarTo) setSimilarTo(null)
          else setCursor(-1)
          break
        default:
          break
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [
    columnCount,
    cursor,
    detail,
    helpOpen,
    items,
    moveCursor,
    openDetail,
    pickerOpen,
    selection,
    showSimilar,
    similarTo,
    tagDialogOpen,
    targetIds,
    toggleFavorite,
    toggleSelection,
    view,
  ])

  const activeFilterChips = useMemo(() => {
    const chips: { label: string; clear: () => void }[] = []
    filters.tags.forEach((tag) =>
      chips.push({
        label: tag,
        clear: () => changeFilters({ tags: filters.tags.filter((entry) => entry !== tag) }),
      }),
    )
    if (filters.look)
      chips.push({
        label: LOOK_LABEL[filters.look as Look] ?? filters.look,
        clear: () => changeFilters({ look: '' }),
      })
    if (filters.folder)
      chips.push({ label: filters.folder, clear: () => changeFilters({ folder: '' }) })
    if (filters.favorite)
      chips.push({ label: 'Favoriten', clear: () => changeFilters({ favorite: false }) })
    if (filters.only_missing)
      chips.push({ label: 'Fehlende', clear: () => changeFilters({ only_missing: false }) })
    if (filters.date_from || filters.date_to)
      chips.push({
        label: `${filters.date_from || '...'} bis ${filters.date_to || '...'}`,
        clear: () => changeFilters({ date_from: '', date_to: '' }),
      })
    if (filters.duration_min || filters.duration_max)
      chips.push({
        label: `${filters.duration_min || '0'}-${filters.duration_max || '...'} s`,
        clear: () => changeFilters({ duration_min: '', duration_max: '' }),
      })
    return chips
  }, [filters, changeFilters])

  const sortOptions = useMemo(
    () =>
      filters.collection
        ? ([['collection_pos', 'Reihenfolge in der Sammlung'], ...SORT_OPTIONS] as [
            string,
            string,
          ][])
        : SORT_OPTIONS,
    [filters.collection],
  )

  const busy = (stats?.queue.running ?? 0) > 0 || stats?.scanning

  if (phase === 'prüfen') {
    return (
      <div className="login-page">
        <div className="spinner" />
      </div>
    )
  }

  if (phase === 'anmelden') {
    return <Login onSuccess={() => void bootstrap()} />
  }

  if (phase === 'wizard' && setupStatus) {
    return (
      <SetupWizard
        status={setupStatus}
        onDone={() => {
          setPhase('bereit')
          notify('Einrichtung abgeschlossen', 'ok')
          refreshStats()
        }}
      />
    )
  }

  return (
    <div className={`shell${selection.length > 0 ? ' selecting' : ''}`}>
      <nav className="rail">
        <div className="rail-mark">
          <IconLogo size={17} />
        </div>
        {(
          [
            ['library', 'Bibliothek', <IconLibrary key="l" />],
            ['collections', 'Sammlungen', <IconCollection key="c" />],
            ['upload', 'Hochladen', <IconUpload key="u" />],
            ['stats', 'Bibliothek in Zahlen', <IconStats key="s" />],
            ['tools', 'Werkzeuge', <IconTools key="t" />],
          ] as [View, string, JSX.Element][]
        ).map(([key, label, icon]) => (
          <button
            key={key}
            className={`rail-btn${view === key ? ' active' : ''}`}
            onClick={() => setView(key)}
            aria-label={label}
          >
            {icon}
            <span className="tip">{label}</span>
          </button>
        ))}
        <div className="rail-spacer" />
        <button
          className="rail-btn"
          aria-label="Tastaturkürzel"
          onClick={() => setHelpOpen(true)}
        >
          <IconKeyboard size={17} />
          <span className="tip">Tastatur</span>
        </button>
        <ThemeToggle />
        <button
          className="rail-btn"
          aria-label="Abmelden"
          onClick={async () => {
            await api.logout()
            setPhase('anmelden')
          }}
        >
          <IconLogout size={17} />
          <span className="tip">Abmelden</span>
        </button>
      </nav>

      {view === 'library' && (
        <FilterPanel
          facets={facets}
          filters={filters}
          collapsed={!panelOpen}
          onChange={changeFilters}
          onReset={() => {
            setSearchDraft('')
            setSimilarTo(null)
            setFilters({ ...EMPTY_FILTERS, sort: filters.sort })
          }}
        />
      )}

      <main className="main">
        <header className="topbar">
          {view === 'library' && (
            <button
              className="btn ghost"
              onClick={() => setPanelOpen((open) => !open)}
              aria-label="Filter ein- und ausblenden"
            >
              <IconFilter />
            </button>
          )}

          <div className="search">
            <span className="icon">
              <IconSearch />
            </span>
            <input
              ref={searchRef}
              value={searchDraft}
              placeholder="Suchen: Dateiname, Kamera oder Bildinhalt"
              onChange={(event) => {
                setSearchDraft(event.target.value)
                setSimilarTo(null)
                if (view !== 'library') setView('library')
              }}
            />
            <div className="modes">
              {(
                [
                  ['auto', 'Auto'],
                  ['text', 'Text'],
                  ['semantic', 'Inhalt'],
                ] as [Filters['mode'], string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  className={filters.mode === key ? 'on' : ''}
                  onClick={() => changeFilters({ mode: key })}
                  title={
                    key === 'semantic'
                      ? 'Sucht nach dem, was im Bild zu sehen ist'
                      : key === 'text'
                        ? 'Sucht in Dateinamen, Tags und Metadaten'
                        : 'Kombiniert beide Verfahren'
                  }
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {view === 'library' && (
            <>
              <select
                className="sort-select"
                value={filters.sort}
                onChange={(event) => changeFilters({ sort: event.target.value })}
              >
                {sortOptions.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <button
                className="btn ghost"
                onClick={() => setDense((value) => !value)}
                title={dense ? 'Größere Kacheln' : 'Mehr Kacheln pro Reihe'}
              >
                <IconLibrary size={16} />
              </button>
            </>
          )}

          {busy && <span className="spinner" title="Es laufen Hintergrundaufgaben" />}
          {busy && <div className="progress-line" />}
        </header>

        <div className="content">
          {view === 'library' && (
            <>
              {similarTo && (
                <div className="context-bar">
                  <IconSimilar size={14} />
                  <span>
                    Ähnlich zu <strong>{similarTo.filename}</strong>
                  </span>
                  <button className="btn ghost small" onClick={() => setSimilarTo(null)}>
                    <IconClose size={11} /> Zurück zur Bibliothek
                  </button>
                </div>
              )}

              {!similarTo && activeCollection && (
                <div className="context-bar">
                  <IconCollection size={14} />
                  <span>
                    Sammlung <strong>{activeCollection.name}</strong>
                  </span>
                  <button
                    className="btn ghost small"
                    onClick={() => changeFilters({ collection: null })}
                  >
                    <IconClose size={11} /> Sammlung verlassen
                  </button>
                </div>
              )}

              <div className="result-bar">
                <span className="result-count">
                  {loading ? 'lädt' : `${total.toLocaleString('de-DE')} Clips`}
                  {mode === 'semantic' && ' nach Bildinhalt'}
                  {mode === 'hybrid' && ' nach Name und Bildinhalt'}
                  {mode === 'similar' && ' mit ähnlichem Bildinhalt'}
                </span>
                <div className="active-filters">
                  {activeFilterChips.map((chip) => (
                    <span className="active-filter" key={chip.label}>
                      {chip.label}
                      <button onClick={chip.clear} aria-label="Filter entfernen">
                        <IconClose size={10} />
                      </button>
                    </span>
                  ))}
                </div>
                {freshCount > 0 && !similarTo && (
                  <button className="btn small" onClick={() => void loadPage(0, true)}>
                    {freshCount} neue Clips laden
                  </button>
                )}
              </div>

              {loading ? (
                <div className={`grid${dense ? ' dense' : ''}`}>
                  {Array.from({ length: 12 }).map((_, index) => (
                    <div className="skeleton" key={index}>
                      <div className="sk-frame" />
                      <div className="sk-line" />
                      <div className="sk-line short" />
                    </div>
                  ))}
                </div>
              ) : items.length === 0 ? (
                <div className="empty">
                  <IconFilm size={44} />
                  <h3>Nichts gefunden</h3>
                  <p>
                    {similarTo
                      ? similarStatus === 'ready'
                        ? 'Zu diesem Clip passt inhaltlich nichts anderes in der Bibliothek.'
                        : 'Für diesen Clip wurde noch keine Bildanalyse gerechnet. Sobald die inhaltliche Suche durch ist, funktioniert das hier.'
                      : filters.collection
                        ? 'Diese Sammlung ist noch leer. Markier in der Bibliothek Clips und leg sie über die Auswahlleiste hinein.'
                        : filters.q
                          ? 'Versuch einen anderen Suchbegriff oder schalte oben rechts auf "Inhalt" um, dann wird nach dem gesucht, was im Bild zu sehen ist.'
                          : stats?.clips === 0
                            ? 'Die Bibliothek ist noch leer. Leg Dateien in den Medienordner oder lade sie hier hoch.'
                            : 'Mit diesen Filtern bleibt nichts übrig.'}
                  </p>
                </div>
              ) : (
                <>
                  <div className={`grid${dense ? ' dense' : ''}`} ref={gridRef}>
                    {items.map((clip, index) => (
                      <ClipCard
                        key={clip.id}
                        clip={clip}
                        index={index}
                        selected={selection.includes(clip.id)}
                        selecting={selection.length > 0}
                        focused={cursor === index}
                        onOpen={openDetail}
                        onToggle={toggleSelection}
                        onFocus={setCursor}
                      />
                    ))}
                  </div>
                  <div ref={sentinel} style={{ height: 1 }} />
                  {loadingMore && (
                    <div style={{ display: 'grid', placeItems: 'center', padding: 24 }}>
                      <span className="spinner" />
                    </div>
                  )}
                </>
              )}
            </>
          )}

          {view === 'collections' && (
            <CollectionsView
              notify={notify}
              onOpen={openCollection}
              refreshKey={collectionsKey}
            />
          )}

          {view === 'upload' && (
            <UploadView
              organizeUploads
              pattern="Jahr/Monat/Kamera"
              onUploaded={() => {
                notify('Upload fertig, Clip wird eingelesen', 'ok')
                window.setTimeout(() => void loadPage(0, true), 1200)
              }}
            />
          )}

          {view === 'stats' && <StatsView stats={stats} />}

          {view === 'tools' && (
            <ToolsView
              stats={stats}
              notify={notify}
              onLibraryChanged={() => {
                void loadPage(0, true)
                refreshStats()
              }}
            />
          )}
        </div>
      </main>

      {selection.length > 0 && (
        <div className="selection-bar">
          <span className="count">{selection.length}</span>
          <a className="btn" href={api.zipUrl(selection)}>
            <IconDownload size={13} /> Als ZIP laden
          </a>

          <div className="collection-anchor">
            <button className="btn" onClick={() => setPickerOpen((open) => !open)}>
              <IconCollection size={13} /> Sammlung
            </button>
            {pickerOpen && (
              <CollectionPicker
                clipIds={selection}
                onClose={() => setPickerOpen(false)}
                onChanged={(message) => {
                  notify(message, 'ok')
                  setCollectionsKey((key) => key + 1)
                  if (filters.collection) void loadPage(0, true)
                }}
              />
            )}
          </div>

          <button className="btn" onClick={() => setTagDialogOpen(true)}>
            <IconTag size={13} /> Tags
          </button>
          <button
            className="btn"
            onClick={async () => {
              await api.batchTags({ clip_ids: selection, favorite: true })
              notify('Als Favoriten markiert', 'ok')
              await refreshClips(selection)
            }}
          >
            <IconStar size={13} /> Favorit
          </button>

          {activeCollection && (
            <button
              className="btn"
              onClick={async () => {
                const result = await api.removeFromCollection(activeCollection.id, selection)
                notify(`${result.removed} aus "${activeCollection.name}" entfernt`, 'ok')
                setSelection([])
                setCollectionsKey((key) => key + 1)
                void loadPage(0, true)
              }}
            >
              <IconClose size={12} /> Aus Sammlung
            </button>
          )}

          <div className="sep" />
          <button
            className="btn ghost"
            onClick={() => setSelection(items.map((clip) => clip.id))}
          >
            <IconCheck size={12} /> Alle
          </button>
          <button className="btn ghost" onClick={() => setSelection([])}>
            <IconClose size={12} />
          </button>
        </div>
      )}

      {tagDialogOpen && targetClips.length > 0 && (
        <BatchTagDialog
          clips={targetClips}
          onClose={() => setTagDialogOpen(false)}
          onApply={applyBatchTags}
        />
      )}

      {helpOpen && <ShortcutsHelp onClose={() => setHelpOpen(false)} />}

      {detail && (
        <ClipDetail
          clip={detail}
          onClose={() => setDetail(null)}
          onChange={patchClipInList}
          onNavigate={navigateDetail}
          onSimilar={showSimilar}
          onDeleted={(id) => {
            setItems((current) => current.filter((clip) => clip.id !== id))
            setDetail(null)
          }}
          onTagClick={(tag) => {
            setDetail(null)
            changeFilters({ tags: [tag] })
            setView('library')
          }}
          notify={notify}
        />
      )}

      <Toasts toasts={toasts} />
    </div>
  )
}
