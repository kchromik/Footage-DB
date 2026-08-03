import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from './lib/api'
import { EMPTY_FILTERS } from './lib/types'
import type { Clip, Facets, Filters, SetupStatus, Stats } from './lib/types'
import { useEvents } from './lib/useEvents'
import { LOOK_LABEL } from './lib/format'
import type { Look } from './lib/types'
import { ClipCard } from './components/ClipCard'
import { ClipDetail } from './components/ClipDetail'
import { FilterPanel } from './components/FilterPanel'
import { Login } from './components/Login'
import { SetupWizard } from './components/SetupWizard'
import { StatsView } from './components/StatsView'
import { ToolsView } from './components/ToolsView'
import { UploadView } from './components/UploadView'
import { Toasts, useToasts } from './components/Toasts'
import { ThemeToggle } from './components/ThemeToggle'
import {
  IconCheck,
  IconClose,
  IconDownload,
  IconFilm,
  IconFilter,
  IconLibrary,
  IconLogo,
  IconLogout,
  IconSearch,
  IconStar,
  IconStats,
  IconTools,
  IconUpload,
} from './components/Icons'

type View = 'library' | 'upload' | 'stats' | 'tools'
type Phase = 'prüfen' | 'anmelden' | 'wizard' | 'bereit'

const PAGE_SIZE = 60

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
  const [detail, setDetail] = useState<Clip | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)

  const { toasts, notify } = useToasts()
  const searchRef = useRef<HTMLInputElement>(null)
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
        if (replace) setFreshCount(0)
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

  useEffect(() => {
    if (phase !== 'bereit') return
    void loadPage(0, true)
  }, [phase, loadPage])

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

  /* Unendliches Nachladen beim Scrollen */
  useEffect(() => {
    const node = sentinel.current
    if (!node || view !== 'library') return
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
  }, [items.length, total, loading, loadingMore, loadPage, view])

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

  /* -------------------------------------------------------- Tastatur */

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const typing =
        event.target instanceof HTMLElement &&
        ['INPUT', 'TEXTAREA'].includes(event.target.tagName)
      if (event.key === '/' && !typing) {
        event.preventDefault()
        setView('library')
        searchRef.current?.focus()
      }
      if (event.key === 'Escape' && !detail) {
        if (selection.length > 0) setSelection([])
        else if (typing) (event.target as HTMLElement).blur()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [detail, selection.length])

  /* -------------------------------------------------------------- Detail */

  const openDetail = useCallback(
    async (clip: Clip) => {
      setDetail(clip)
      try {
        setDetail(await api.clip(clip.id))
      } catch {
        /* Kurzfassung reicht auch */
      }
    },
    [],
  )

  const navigateDetail = useCallback(
    (direction: -1 | 1) => {
      if (!detail) return
      const index = items.findIndex((clip) => clip.id === detail.id)
      const next = items[index + direction]
      if (next) void openDetail(next)
    },
    [detail, items, openDetail],
  )

  const patchClipInList = useCallback((clip: Clip) => {
    setItems((current) => current.map((entry) => (entry.id === clip.id ? clip : entry)))
    setDetail((current) => (current && current.id === clip.id ? clip : current))
  }, [])

  /* ------------------------------------------------------------ Ableitung */

  const changeFilters = useCallback((patch: Partial<Filters>) => {
    setFilters((current) => ({ ...current, ...patch }))
    setSelection([])
  }, [])

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
                {SORT_OPTIONS.map(([value, label]) => (
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
              <div className="result-bar">
                <span className="result-count">
                  {loading ? 'lädt' : `${total.toLocaleString('de-DE')} Clips`}
                  {mode === 'semantic' && ' nach Bildinhalt'}
                  {mode === 'hybrid' && ' nach Name und Bildinhalt'}
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
                {freshCount > 0 && (
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
                    {filters.q
                      ? 'Versuch einen anderen Suchbegriff oder schalte oben rechts auf "Inhalt" um, dann wird nach dem gesucht, was im Bild zu sehen ist.'
                      : stats?.clips === 0
                        ? 'Die Bibliothek ist noch leer. Leg Dateien in den Medienordner oder lade sie hier hoch.'
                        : 'Mit diesen Filtern bleibt nichts übrig.'}
                  </p>
                </div>
              ) : (
                <>
                  <div className={`grid${dense ? ' dense' : ''}`}>
                    {items.map((clip, index) => (
                      <ClipCard
                        key={clip.id}
                        clip={clip}
                        index={index}
                        selected={selection.includes(clip.id)}
                        selecting={selection.length > 0}
                        onOpen={openDetail}
                        onToggle={toggleSelection}
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
          <button
            className="btn"
            onClick={async () => {
              const name = window.prompt('Welches Tag soll auf alle ausgewählten Clips?')
              if (!name?.trim()) return
              await api.batchTags({ clip_ids: selection, add: [name.trim()] })
              notify(`"${name.trim()}" gesetzt`, 'ok')
              void loadPage(0, true)
            }}
          >
            Tag setzen
          </button>
          <button
            className="btn"
            onClick={async () => {
              await api.batchTags({ clip_ids: selection, favorite: true })
              notify('Als Favoriten markiert', 'ok')
              void loadPage(0, true)
            }}
          >
            <IconStar size={13} /> Favorit
          </button>
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

      {detail && (
        <ClipDetail
          clip={detail}
          onClose={() => setDetail(null)}
          onChange={patchClipInList}
          onNavigate={navigateDetail}
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
