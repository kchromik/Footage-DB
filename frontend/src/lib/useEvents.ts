import { useEffect, useRef } from 'react'

export interface LiveEvent {
  type: 'clip' | 'scan' | 'queue' | 'upload'
  [key: string]: unknown
}

/**
 * Haelt eine Verbindung zum Ereignisstrom des Servers offen und verbindet
 * sich nach einem Abbruch selbstaendig neu.
 */
export function useEvents(onEvent: (event: LiveEvent) => void, enabled: boolean) {
  const handler = useRef(onEvent)
  handler.current = onEvent

  useEffect(() => {
    if (!enabled) return
    let source: EventSource | null = null
    let retry: number | undefined
    let closed = false

    const connect = () => {
      if (closed) return
      source = new EventSource('/api/events')
      source.onmessage = (message) => {
        try {
          handler.current(JSON.parse(message.data) as LiveEvent)
        } catch {
          /* unvollstaendige Nachricht ignorieren */
        }
      }
      source.onerror = () => {
        source?.close()
        if (closed) return
        retry = window.setTimeout(connect, 4000)
      }
    }

    connect()
    return () => {
      closed = true
      window.clearTimeout(retry)
      source?.close()
    }
  }, [enabled])
}
