import { useEffect } from 'react'
import { IconClose, IconKeyboard } from './Icons'

interface Props {
  onClose: () => void
}

const GRUPPEN: { title: string; rows: [string[], string][] }[] = [
  {
    title: 'Sichten',
    rows: [
      [['J', '→'], 'Nächster Clip'],
      [['K', '←'], 'Vorheriger Clip'],
      [['↑', '↓'], 'Eine Reihe hoch oder runter'],
      [['Enter'], 'Clip öffnen'],
      [['Esc'], 'Schließen oder Auswahl aufheben'],
    ],
  },
  {
    title: 'Bewerten und markieren',
    rows: [
      [['F'], 'Favorit an und aus'],
      [['X', 'Leertaste'], 'Clip markieren'],
      [['Umschalt', 'X'], 'Bis hierhin markieren'],
      [['A'], 'Alles markieren'],
      [['T'], 'Tags für die Markierung'],
      [['C'], 'In eine Sammlung legen'],
    ],
  },
  {
    title: 'Sonstiges',
    rows: [
      [['/'], 'In die Suche springen'],
      [['S'], 'Ähnliche Clips zum offenen Clip'],
      [['?'], 'Diese Übersicht'],
    ],
  },
]

export function ShortcutsHelp({ onClose }: Props) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' || event.key === '?') {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [onClose])

  return (
    <div
      className="overlay"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="dialog shortcuts" role="dialog" aria-label="Tastaturkürzel">
        <div className="dialog-head">
          <div>
            <h3>
              <IconKeyboard size={15} /> Tastatur
            </h3>
            <p>Zum Sichten von viel Material, ohne die Maus anzufassen.</p>
          </div>
          <button className="round-btn" onClick={onClose} aria-label="Schließen">
            <IconClose size={14} />
          </button>
        </div>

        <div className="dialog-body shortcut-groups">
          {GRUPPEN.map((gruppe) => (
            <div className="shortcut-group" key={gruppe.title}>
              <div className="label">{gruppe.title}</div>
              {gruppe.rows.map(([keys, description]) => (
                <div className="shortcut-row" key={description}>
                  <span className="keys">
                    {keys.map((key, index) => (
                      <span key={key}>
                        {index > 0 && <i className="oder">oder</i>}
                        <kbd>{key}</kbd>
                      </span>
                    ))}
                  </span>
                  <span className="what">{description}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
