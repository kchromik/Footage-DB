import { useCallback, useRef, useState } from 'react'
import { api } from './api'

export type UploadState = 'wartet' | 'läuft' | 'fertig' | 'fehler' | 'abgebrochen'

export interface UploadTask {
  key: string
  file: File
  tags: string[]
  uploadId?: string
  sent: number
  total: number
  state: UploadState
  error?: string
  clipId?: number
  targetPath?: string
}

const PARALLEL_CHUNKS = 2

/**
 * Lädt Dateien blockweise hoch. Bricht die Verbindung ab, merkt sich der
 * Server die bereits erhaltenen Blöcke und der nächste Versuch macht dort
 * weiter, statt eine 30-GB-Datei erneut zu schicken.
 */
export function useUploader(onFinished: (clipId: number) => void) {
  const [tasks, setTasks] = useState<UploadTask[]>([])
  const queue = useRef<UploadTask[]>([])
  const running = useRef(false)
  const aborted = useRef(new Set<string>())

  const update = useCallback((key: string, patch: Partial<UploadTask>) => {
    setTasks((current) =>
      current.map((task) => (task.key === key ? { ...task, ...patch } : task)),
    )
  }, [])

  const runOne = useCallback(
    async (task: UploadTask) => {
      update(task.key, { state: 'läuft' })
      try {
        const init = await api.initUpload(
          task.file.name,
          task.file.size,
          '',
          task.tags,
        )
        const received = new Set(init.received)
        update(task.key, {
          uploadId: init.id,
          sent: received.size * init.chunk_size,
        })

        const pending: number[] = []
        for (let index = 0; index < init.chunk_count; index += 1) {
          if (!received.has(index)) pending.push(index)
        }

        let done = received.size
        let cursor = 0

        const worker = async () => {
          while (cursor < pending.length) {
            if (aborted.current.has(task.key)) return
            const index = pending[cursor]
            cursor += 1
            const start = index * init.chunk_size
            const end = Math.min(start + init.chunk_size, task.file.size)
            await api.uploadChunk(init.id, index, task.file.slice(start, end))
            done += 1
            update(task.key, {
              sent: Math.min(task.file.size, done * init.chunk_size),
            })
          }
        }

        await Promise.all(
          Array.from({ length: Math.min(PARALLEL_CHUNKS, pending.length || 1) }, worker),
        )

        if (aborted.current.has(task.key)) {
          await api.abortUpload(init.id).catch(() => undefined)
          update(task.key, { state: 'abgebrochen' })
          return
        }

        const result = await api.completeUpload(init.id)
        update(task.key, {
          state: 'fertig',
          sent: task.file.size,
          clipId: result.clip_id,
          targetPath: result.path,
        })
        onFinished(result.clip_id)
      } catch (error) {
        update(task.key, { state: 'fehler', error: (error as Error).message })
      }
    },
    [onFinished, update],
  )

  const pump = useCallback(async () => {
    if (running.current) return
    running.current = true
    try {
      while (queue.current.length > 0) {
        const next = queue.current.shift()
        if (next) await runOne(next)
      }
    } finally {
      running.current = false
    }
  }, [runOne])

  const add = useCallback(
    (files: File[], tags: string[] = []) => {
      const fresh = files.map((file) => ({
        key: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 7)}`,
        file,
        tags,
        sent: 0,
        total: file.size,
        state: 'wartet' as UploadState,
      }))
      setTasks((current) => [...fresh, ...current])
      queue.current.push(...fresh)
      void pump()
    },
    [pump],
  )

  const cancel = useCallback((key: string) => {
    aborted.current.add(key)
    queue.current = queue.current.filter((task) => task.key !== key)
    setTasks((current) =>
      current.map((task) =>
        task.key === key && task.state !== 'fertig'
          ? { ...task, state: 'abgebrochen' }
          : task,
      ),
    )
  }, [])

  const retry = useCallback(
    (key: string) => {
      aborted.current.delete(key)
      setTasks((current) => {
        const task = current.find((entry) => entry.key === key)
        if (task) {
          queue.current.push({ ...task, sent: 0, state: 'wartet' })
          void pump()
        }
        return current.map((entry) =>
          entry.key === key ? { ...entry, state: 'wartet', error: undefined, sent: 0 } : entry,
        )
      })
    },
    [pump],
  )

  const clearFinished = useCallback(() => {
    setTasks((current) => current.filter((task) => task.state !== 'fertig'))
  }, [])

  const active = tasks.some((task) => task.state === 'läuft' || task.state === 'wartet')

  return { tasks, add, cancel, retry, clearFinished, active }
}
