import { useCallback, useState } from 'react'

export interface Toast {
  id: number
  message: string
  kind: 'info' | 'ok' | 'error'
}

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([])

  const notify = useCallback((message: string, kind: 'info' | 'ok' | 'error' = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((current) => [...current, { id, message, kind }])
    window.setTimeout(
      () => setToasts((current) => current.filter((toast) => toast.id !== id)),
      kind === 'error' ? 7000 : 4000,
    )
  }, [])

  return { toasts, notify }
}

export function Toasts({ toasts }: { toasts: Toast[] }) {
  if (toasts.length === 0) return null
  return (
    <div className="toasts">
      {toasts.map((toast) => (
        <div className={`toast ${toast.kind}`} key={toast.id}>
          <span className="bar" />
          <span>{toast.message}</span>
        </div>
      ))}
    </div>
  )
}
