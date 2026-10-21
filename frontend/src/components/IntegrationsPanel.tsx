import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { Integrations } from '../lib/types'

interface Props {
  notify: (message: string, kind?: 'ok' | 'error') => void
}

export function IntegrationsPanel({ notify }: Props) {
  const [data, setData] = useState<Integrations | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [token, setToken] = useState('')
  const [guide, setGuide] = useState<'desktop' | 'other'>('desktop')

  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const result = await api.integrations()
        if (active) { setData(result); setError('') }
      } catch (err) {
        if (active) setError((err as Error).message)
      }
      if (active) timer = setTimeout(poll, 5000)
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [])

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      setData(await api.integrations())
    } catch (err) { notify((err as Error).message, 'error') }
    finally { setBusy(false) }
  }

  const copy = async (value: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value)
      else {
        // NAS-Oberflächen laufen oft per HTTP, dort fehlt die Clipboard-API.
        const field = document.createElement('textarea')
        field.value = value
        field.style.position = 'fixed'
        field.style.opacity = '0'
        document.body.appendChild(field)
        field.select()
        const copied = document.execCommand('copy')
        field.remove()
        if (!copied) throw new Error('Bitte den Text markieren und manuell kopieren.')
      }
      notify('Kopiert', 'ok')
    } catch (err) { notify((err as Error).message, 'error') }
  }

  const counts = data?.analysis.counts ?? {}
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0)
  const config = data ? `[mcp_servers.footagedb]\nurl = ${JSON.stringify(data.mcp.url)}\nhttp_headers = { Authorization = ${JSON.stringify(`Bearer ${token || 'DEIN_MCP_SCHLUESSEL'}`)} }` : ''

  return <section className="card-block integrations" aria-labelledby="integrations-title">
    <div className="integration-heading">
      <div><h3 id="integrations-title">KI & MCP</h3><p>Deine Bibliothek als Quelle für andere KIs.</p></div>
      <span className="integration-badge">Nur Lesezugriff</span>
    </div>
    {error && <p className="integration-error" role="alert">{error}</p>}
    {!data && !error && <p className="note">Verbindung wird geprüft …</p>}
    {data && <>
      <div className="integration-columns">
        <div className="integration-section">
          <div className="label">01 / Inhaltsanalyse</div>
          <h4>Codex im Hintergrund</h4>
          <p>Beschreibungen, Tags und Einzelbilder mit Zeitstempeln für alle bestehenden,
            neuen und geänderten Clips. Die Analyse nutzt dein ChatGPT-Abo und sendet
            ausgewählte Bilder an OpenAI. Ohne Audio-Transkription.</p>
          <div className="integration-state" role="status">
            <span className={`integration-dot${data.codex.authenticated ? ' connected' : ''}`} />
            {!data.codex.installed ? 'Codex CLI fehlt im Container' : data.codex.authenticated
              ? data.analysis.enabled ? 'Angemeldet · Automatik aktiv' : 'Angemeldet · Automatik pausiert'
              : data.codex.state === 'pending' ? 'Wartet auf Gerätecode-Anmeldung' : 'Anmeldung erforderlich'}
          </div>
          {!data.codex.authenticated && <button className="btn primary" disabled={busy || !data.codex.installed || data.codex.state === 'pending'}
            onClick={() => act(() => api.codexLogin())}>Mit ChatGPT anmelden</button>}
          {data.codex.state === 'pending' && !data.codex.authenticated && <div className="device-login">
            {data.codex.code ? <>
              <span className="label">Dein Gerätecode</span>
              <button className="device-code mono" onClick={() => copy(data.codex.code!)} title="Gerätecode kopieren">{data.codex.code}</button>
              {data.codex.url && <a className="btn primary" href={data.codex.url} target="_blank" rel="noreferrer">Bei OpenAI bestätigen ↗</a>}
              <p className="note">Code auf der OpenAI-Seite eingeben. Danach startet die Analyse automatisch.
                Falls nötig, Gerätecode-Anmeldung in den Sicherheitseinstellungen deines ChatGPT-Kontos aktivieren.</p>
            </> : <p className="note">Gerätecode wird angefordert …</p>}
          </div>}
          {data.codex.error && <p className="integration-error" role="alert">{data.codex.error}</p>}
          <div className="analysis-count"><strong className="mono">{counts.ready ?? 0}<span> / {total}</span></strong><span>Clips analysiert</span></div>
          <progress max={Math.max(total, 1)} value={counts.ready ?? 0} aria-label="Analysierte Clips" />
          <p className="note">{counts.running ?? 0} aktiv · {counts.pending ?? 0} ausstehend · {counts.failed ?? 0} fehlgeschlagen</p>
          {data.analysis.pause_until && <p className="note">Kontingentpause bis {new Date(data.analysis.pause_until * 1000).toLocaleTimeString('de-DE')}. Danach geht es automatisch weiter.</p>}
          {data.analysis.error && <p className="integration-error">{data.analysis.error}</p>}
          <div className="integration-actions">
            <button className="btn small" disabled={busy} onClick={() => act(() => api.analysisEnabled(!data.analysis.enabled))}>
              {data.analysis.enabled ? 'Automatik pausieren' : 'Automatik fortsetzen'}</button>
            {(counts.failed ?? 0) > 0 && <button className="btn small" disabled={busy} onClick={() => act(() => api.retryAnalysis())}>Fehlgeschlagene erneut versuchen</button>}
          </div>
        </div>
        <div className="integration-section">
          <div className="label">02 / MCP-Verbindung</div>
          <h4>Clips finden und herunterladen</h4>
          <p>Die angebundene KI kann suchen, alle Clip-Informationen und Frames lesen
            und vollständige Originaldateien herunterladen.</p>
          <label className="label" htmlFor="mcp-url">Server-URL · Streamable HTTP</label>
          <div className="integration-copy"><input id="mcp-url" className="field mono" value={data.mcp.url} readOnly /><button className="btn" onClick={() => copy(data.mcp.url)}>Kopieren</button></div>
          <label className="label" htmlFor="mcp-token">MCP-Zugangsschlüssel</label>
          <div className="integration-copy"><input id="mcp-token" className="field mono" type="password" value={token} placeholder="Geschützt · zum Kopieren anzeigen" readOnly />
            <button className="btn" disabled={busy} onClick={() => token ? copy(token) : act(async () => { setToken((await api.mcpToken()).token) })}>{token ? 'Kopieren' : 'Anzeigen'}</button></div>
          <p className="note">Anmeldung: Header <code>Authorization: Bearer DEIN_MCP_SCHLUESSEL</code>.
            Dieser Schlüssel gewährt ausschließlich Lesezugriff, keinen Zugang zu den Einstellungen.</p>
          <details><summary>Schlüssel ersetzen</summary><p className="note">Bestehende MCP-Verbindungen und Downloadlinks verlieren sofort ihre Gültigkeit.</p>
            <button className="btn small" disabled={busy} onClick={() => act(async () => { setToken((await api.mcpToken(true)).token); notify('Neuen Schlüssel in deinen MCP-Clients eintragen.', 'ok') })}>Neuen Schlüssel erzeugen</button></details>
        </div>
      </div>
      <div className="integration-guide">
        <div className="integration-heading"><h4>Auf deinem Mac einrichten</h4><div className="integration-actions">
          <button className={`btn small${guide === 'desktop' ? ' primary' : ''}`} aria-pressed={guide === 'desktop'} onClick={() => setGuide('desktop')}>ChatGPT / Codex</button>
          <button className={`btn small${guide === 'other' ? ' primary' : ''}`} aria-pressed={guide === 'other'} onClick={() => setGuide('other')}>Andere MCP-Clients</button>
        </div></div>
        {guide === 'desktop' ? <>
          <ol><li>Für eine <strong>lokal ausgeführte MCP-Verbindung</strong> in Codex bzw. dem lokalen Work-/Codex-Modus der ChatGPT-Desktop-App diese Konfiguration in <code>~/.codex/config.toml</code> ergänzen.</li>
            <li>Den MCP-Schlüssel oben anzeigen; die Konfiguration enthält ihn dann automatisch. Vorhandene Konfiguration beibehalten.</li>
            <li>Die App neu starten, FootageDB aktivieren und einen neuen Chat beginnen.</li></ol>
          <pre className="integration-config"><code>{config}</code></pre>
          <button className="btn small" disabled={!token} onClick={() => copy(config)}>Konfiguration kopieren</button>
          <p className="note">Bei einer cloudseitigen ChatGPT-Verbindung reicht eine private NAS-IP nicht aus.
            Dafür wird eine vom Dienst erreichbare Verbindung mit passender Anmeldung benötigt.
            Die Anleitung oben gilt für lokale MCP-Clients im Heimnetz oder VPN.</p>
          <a className="note" href="https://learn.chatgpt.com/docs/config-file/config-reference" target="_blank" rel="noreferrer">Offizielle MCP-Konfiguration ↗</a>
        </> : <>
          <ol><li>Neuen MCP-Server mit Transport <strong>Streamable HTTP</strong> hinzufügen.</li>
            <li>Die Server-URL oben einsetzen und den Header <code>Authorization</code> mit dem Wert <code>Bearer DEIN_MCP_SCHLUESSEL</code> hinterlegen.</li>
            <li>Client und NAS müssen sich im gleichen Netz oder VPN erreichen können.</li></ol>
          <p className="note">Verfügbare Werkzeuge: <code>search_clips</code>, <code>get_clip</code>, <code>get_frame</code>, <code>get_download</code>, <code>list_library</code>.</p>
        </>}
        <div className="integration-example">„Finde ruhige B-Roll von Natur oder Landschaft, zeige mir passende Frames und lade die Originaldatei des besten Clips herunter.“</div>
        <p className="note">Downloadlinks gelten eine Stunde und unterstützen fortsetzbare Downloads.
          Die KI speichert die Datei mit ihrem eigenen Downloadwerkzeug auf deinem Mac.
          Zeitstempel beziehen sich auf Stichprobenbilder; den finalen Schnitt legt dein Schnittprogramm fest.</p>
      </div>
    </>}
  </section>
}
