import { useState } from 'react'
import { api } from '../lib/api'
import { IconLogo } from './Icons'

interface Props {
  onSuccess: () => void
}

export function Login({ onSuccess }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api.login(username, password)
      onSuccess()
    } catch (loginError) {
      setError((loginError as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <form className="login-box" onSubmit={submit}>
        <div className="mark">
          <IconLogo size={20} />
        </div>
        <h1>FootageDB</h1>
        <p className="sub">Deine B-Roll-Bibliothek</p>

        {error && <div className="login-error">{error}</div>}

        <label>
          <span className="label">Benutzer</span>
          <input
            className="field"
            value={username}
            autoFocus
            autoComplete="username"
            onChange={(event) => setUsername(event.target.value)}
          />
        </label>
        <label>
          <span className="label">Passwort</span>
          <input
            className="field"
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>

        <button className="btn primary" style={{ width: '100%', height: 36, justifyContent: 'center', marginTop: 6 }} disabled={busy}>
          {busy ? <span className="spinner" /> : 'Anmelden'}
        </button>
      </form>
    </div>
  )
}
