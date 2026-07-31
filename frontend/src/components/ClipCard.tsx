import { memo, useCallback, useRef, useState } from 'react'
import type { Clip } from '../lib/types'
import { LOOK_COLOR, LOOK_LABEL, formatDate } from '../lib/format'
import { IconCheck, IconFilm } from './Icons'

interface Props {
  clip: Clip
  selected: boolean
  selecting: boolean
  onOpen: (clip: Clip) => void
  onToggle: (clip: Clip, shiftKey: boolean) => void
  index: number
}

const CARD_ASPECT = 16 / 9

function ClipCardInner({ clip, selected, selecting, onOpen, onToggle, index }: Props) {
  const [frame, setFrame] = useState(0)
  const [hovering, setHovering] = useState(false)
  const frameRef = useRef<HTMLDivElement>(null)
  const sprite = clip.sprite

  /* Beim Ziehen der Maus über die Kachel durch die Einzelbilder blättern.
     Genau das macht das Sichten von Material schnell. */
  const handleMove = useCallback(
    (event: React.MouseEvent) => {
      if (!sprite || sprite.count < 2) return
      const box = frameRef.current?.getBoundingClientRect()
      if (!box) return
      const ratio = (event.clientX - box.left) / box.width
      const next = Math.min(sprite.count - 1, Math.max(0, Math.floor(ratio * sprite.count)))
      setFrame((current) => (current === next ? current : next))
    },
    [sprite],
  )

  const scrubStyle = (): React.CSSProperties | undefined => {
    if (!sprite) return undefined
    const tileAspect = sprite.tile_width / Math.max(1, sprite.tile_height)
    const wider = tileAspect >= CARD_ASPECT
    const column = frame % sprite.columns
    const row = Math.floor(frame / sprite.columns)
    return {
      width: wider ? `${(tileAspect / CARD_ASPECT) * 100}%` : '100%',
      height: wider ? '100%' : `${(CARD_ASPECT / tileAspect) * 100}%`,
      backgroundImage: `url(${sprite.url})`,
      backgroundSize: `${sprite.columns * 100}% ${sprite.rows * 100}%`,
      backgroundPosition: `${sprite.columns > 1 ? (column / (sprite.columns - 1)) * 100 : 0}% ${
        sprite.rows > 1 ? (row / (sprite.rows - 1)) * 100 : 0
      }%`,
    }
  }

  const meta = [clip.camera, clip.resolution, formatDate(clip.recorded_at)].filter(Boolean)

  return (
    <article
      className={`card${selected ? ' selected' : ''}`}
      style={{ animationDelay: `${Math.min(index, 24) * 18}ms` }}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || selecting) {
          onToggle(clip, event.shiftKey)
        } else {
          onOpen(clip)
        }
      }}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => {
        setHovering(false)
        setFrame(0)
      }}
    >
      <div className="card-frame" ref={frameRef} onMouseMove={handleMove}>
        {clip.poster_url ? (
          <img src={clip.poster_url} alt="" loading="lazy" decoding="async" />
        ) : (
          <div className="placeholder">
            <IconFilm size={30} />
          </div>
        )}

        {sprite && sprite.count > 1 && (
          <>
            <div className={`scrub${hovering ? ' ready' : ''}`} style={scrubStyle()} />
            <div className="scrub-ticks">
              {Array.from({ length: Math.min(sprite.count, 24) }).map((_, tick) => (
                <i
                  key={tick}
                  className={
                    Math.floor((tick / Math.min(sprite.count, 24)) * sprite.count) === frame
                      ? 'on'
                      : ''
                  }
                />
              ))}
            </div>
          </>
        )}

        <button
          type="button"
          className={`card-select${selected ? ' on' : ''}`}
          aria-label={selected ? 'Auswahl aufheben' : 'Auswählen'}
          onClick={(event) => {
            event.stopPropagation()
            onToggle(clip, event.shiftKey)
          }}
        >
          {selected && <IconCheck size={12} />}
        </button>

        {clip.score !== undefined && (
          <span className="card-score">{Math.round(clip.score * 100)}</span>
        )}

        <div className="card-badges">
          <span />
          {clip.resolution && !clip.score && (
            <span className="badge">{clip.resolution}</span>
          )}
        </div>

        <span className="badge duration">{clip.duration_label}</span>
      </div>

      <div className="card-body">
        <div className="card-name" title={clip.filename}>
          {clip.filename}
        </div>
        <div className="card-meta">
          <span
            className="badge look"
            style={{ ['--look-color' as string]: LOOK_COLOR[clip.look], background: 'none', padding: 0 }}
          >
            {LOOK_LABEL[clip.look]}
          </span>
          {meta.map((entry) => (
            <span key={entry} style={{ display: 'contents' }}>
              <i className="dot" />
              <span
                style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              >
                {entry}
              </span>
            </span>
          ))}
        </div>
      </div>
    </article>
  )
}

export const ClipCard = memo(ClipCardInner)
