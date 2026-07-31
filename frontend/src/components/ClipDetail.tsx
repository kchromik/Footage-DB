import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { Clip, Look } from '../lib/types'
import {
  LOOK_COLOR,
  LOOK_LABEL,
  formatBitrate,
  formatDate,
  formatFps,
} from '../lib/format'
import {
  IconArrowLeft,
  IconArrowRight,
  IconClose,
  IconDownload,
  IconFilm,
  IconRefresh,
  IconStar,
  IconTrash,
} from './Icons'

interface Props {
  clip: Clip
  onClose: () => void
  onChange: (clip: Clip) => void
  onNavigate: (direction: -1 | 1) => void
  onDeleted: (id: number) => void
  onTagClick: (tag: string) => void
  notify: (message: string, kind?: 'ok' | 'error') => void
}

const LOOKS: Look[] = ['log', 'graded', 'hdr', 'rec709', 'unknown']

export function ClipDetail({
  clip,
  onClose,
  onChange,
  onNavigate,
  onDeleted,
  onTagClick,
  notify,
}: Props) {
  const [notes, setNotes] = useState(clip.notes ?? '')
  const [tagDraft, setTagDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    setNotes(clip.notes ?? '')
    setTagDraft('')
  }, [clip.id, clip.notes])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      const typing =
        event.target instanceof HTMLElement &&
        ['INPUT', 'TEXTAREA'].includes(event.target.tagName)
      if (typing) return
      if (event.key === 'ArrowLeft') onNavigate(-1)
      if (event.key === 'ArrowRight') onNavigate(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, onNavigate])

  const patch = async (payload: Record<string, unknown>) => {
    setBusy(true)
    try {
      onChange(await api.updateClip(clip.id, payload))
    } catch (error) {
      notify(`Speichern fehlgeschlagen: ${(error as Error).message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  const manualTags = clip.tags.filter((tag) => tag.source === 'manual')
  const autoTags = clip.tags.filter((tag) => tag.source !== 'manual')

  const addTag = async () => {
    const name = tagDraft.trim()
    if (!name) return
    setTagDraft('')
    await patch({ tags: [...manualTags.map((tag) => tag.name), name] })
  }

  const removeTag = async (name: string) => {
    await patch({
      tags: manualTags.filter((tag) => tag.name !== name).map((tag) => tag.name),
    })
  }

  const specs: [string, string | null][] = [
    ['Aufnahme', clip.recorded_at ? formatDate(clip.recorded_at, true) : null],
    ['Kamera', clip.camera],
    ['Objektiv', clip.lens],
    ['Auflösung', clip.width && clip.height ? `${clip.width} x ${clip.height}` : null],
    ['Bildrate', clip.fps ? `${formatFps(clip.fps)} fps` : null],
    ['Dauer', clip.duration_label],
    ['Codec', clip.video_codec ? clip.video_codec.toUpperCase() : null],
    ['Farbtiefe', clip.bit_depth ? `${clip.bit_depth} Bit` : null],
    ['Farbraum', [clip.color_primaries, clip.color_transfer].filter(Boolean).join(' / ') || null],
    ['Datenrate', formatBitrate(clip.bitrate)],
    [
      'Ton',
      clip.audio_codec
        ? `${clip.audio_codec.toUpperCase()}${
            clip.audio_channels
              ? `, ${clip.audio_channels} ${clip.audio_channels === 1 ? 'Kanal' : 'Kanäle'}`
              : ''
          }`
        : 'keiner',
    ],
    ['Größe', clip.size_label],
    ['Container', clip.container],
    ['Encoder', clip.encoder],
    ['Ordner', clip.folder || '/'],
    ['GPS', clip.gps ? `${clip.gps.lat.toFixed(4)}, ${clip.gps.lon.toFixed(4)}` : null],
  ]

  return (
    <div className="overlay" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="detail" role="dialog" aria-label={clip.filename}>
        <div className="detail-stage">
          <div className="detail-nav">
            <button className="round-btn" onClick={() => onNavigate(-1)} aria-label="Vorheriger Clip">
              <IconArrowLeft />
            </button>
            <button className="round-btn" onClick={() => onNavigate(1)} aria-label="Nächster Clip">
              <IconArrowRight />
            </button>
            <button className="round-btn" onClick={onClose} aria-label="Schließen">
              <IconClose size={15} />
            </button>
          </div>

          {clip.playable ? (
            <video
              ref={videoRef}
              key={clip.id}
              src={clip.play_url}
              controls
              autoPlay
              loop
              playsInline
              preload="metadata"
              poster={clip.poster_url ?? undefined}
            />
          ) : (
            <div className="stage-note">
              <IconFilm size={40} />
              <div>
                {clip.proxy_status === 'failed'
                  ? 'Für diesen Clip konnte keine Vorschau erzeugt werden.'
                  : 'Die Vorschau wird gerade erzeugt.'}
              </div>
              <button
                className="btn small"
                onClick={async () => {
                  await api.reprocess(clip.id, 'proxy')
                  notify('Vorschau wird neu erzeugt')
                }}
              >
                <IconRefresh size={13} /> Erneut versuchen
              </button>
            </div>
          )}
        </div>

        <aside className="detail-side">
          <div className="detail-head">
            <div className="detail-title">{clip.title || clip.filename}</div>
            <div className="detail-path">{clip.path}</div>
          </div>

          <div className="detail-scroll">
            <div className="label" style={{ marginBottom: 8 }}>
              Bildlook
            </div>
            <div className="look-picker">
              {LOOKS.map((look) => (
                <button
                  key={look}
                  className={`look-option${clip.look === look ? ' on' : ''}`}
                  style={{ ['--dot' as string]: LOOK_COLOR[look] }}
                  onClick={() => patch({ look_manual: look === clip.look_auto ? '' : look })}
                  disabled={busy}
                >
                  {LOOK_LABEL[look]}
                </button>
              ))}
            </div>
            {clip.look_reason && !clip.look_manual && (
              <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-faint)' }}>
                Automatisch erkannt: {clip.look_reason}
              </div>
            )}
            {clip.look_manual && (
              <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-faint)' }}>
                Von dir gesetzt. Automatik sagte:{' '}
                {LOOK_LABEL[(clip.look_auto ?? 'unknown') as Look]}
              </div>
            )}

            <div className="divider" />

            <div className="label" style={{ marginBottom: 8 }}>
              Tags
            </div>
            <div className="tag-editor">
              {manualTags.map((tag) => (
                <span className="tag-pill" key={tag.name}>
                  <span onClick={() => onTagClick(tag.name)} style={{ cursor: 'pointer' }}>
                    {tag.name}
                  </span>
                  <button onClick={() => removeTag(tag.name)} aria-label="Tag entfernen">
                    <IconClose size={10} />
                  </button>
                </span>
              ))}
              <input
                className="tag-input"
                placeholder="Tag +"
                value={tagDraft}
                onChange={(event) => setTagDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void addTag()
                  }
                }}
                onBlur={() => void addTag()}
              />
            </div>

            {autoTags.length > 0 && (
              <>
                <div className="label" style={{ margin: '14px 0 8px' }}>
                  Automatisch
                </div>
                <div className="tag-editor">
                  {autoTags.map((tag) => (
                    <button
                      className="tag-pill auto"
                      key={tag.name}
                      onClick={() => onTagClick(tag.name)}
                      title="Danach filtern"
                    >
                      {tag.name}
                    </button>
                  ))}
                </div>
              </>
            )}

            <div className="divider" />

            <div className="label" style={{ marginBottom: 8 }}>
              Notiz
            </div>
            <textarea
              className="field"
              rows={2}
              placeholder="Wofür ist dieser Clip gut?"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              onBlur={() => notes !== (clip.notes ?? '') && patch({ notes })}
            />

            <div className="divider" />

            <div className="label" style={{ marginBottom: 10 }}>
              Technische Daten
            </div>
            <dl className="spec-grid">
              {specs
                .filter(([, value]) => value)
                .map(([name, value]) => (
                  <div key={name} style={{ display: 'contents' }}>
                    <dt>{name}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
            </dl>

            <div className="divider" />
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button
                className="btn small"
                onClick={async () => {
                  await api.reprocess(clip.id, 'all')
                  notify('Clip wird neu eingelesen')
                }}
              >
                <IconRefresh size={12} /> Neu einlesen
              </button>
              <button
                className="btn small danger"
                onClick={async () => {
                  if (!window.confirm(`${clip.filename} aus der Bibliothek entfernen? Die Datei bleibt auf dem NAS.`))
                    return
                  await api.deleteClip(clip.id, false)
                  onDeleted(clip.id)
                  notify('Aus der Bibliothek entfernt')
                }}
              >
                <IconTrash size={12} /> Entfernen
              </button>
            </div>
          </div>

          <div className="detail-actions">
            <a className="btn primary" href={clip.download_url} download>
              <IconDownload size={14} /> Herunterladen
            </a>
            <button
              className="btn"
              onClick={() => patch({ favorite: !clip.favorite })}
              style={clip.favorite ? { color: 'var(--amber)', borderColor: 'var(--amber-line)' } : undefined}
              aria-label="Favorit"
            >
              <IconStar size={14} filled={clip.favorite} />
            </button>
          </div>
        </aside>
      </div>
    </div>
  )
}
