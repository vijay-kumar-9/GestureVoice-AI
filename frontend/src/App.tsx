import { useEffect, useRef, useState } from 'react'

type EngineName = 'gesture' | 'voice'
type EngineInfo = { running: boolean; pid: number | null }
type Engines = Record<EngineName, EngineInfo>
type LogItem = { type: 'log'; timestamp: string; source: string; message: string }
type Incoming =
  | { type: 'snapshot'; engines: Engines; logs: LogItem[]; gesture_enabled?: boolean }
  | { type: 'status'; engines: Engines; gesture_enabled?: boolean }
  | LogItem

const EMPTY: Engines = {
  gesture: { running: false, pid: null },
  voice: { running: false, pid: null },
}

const shortcuts = [
  ['01', 'Cursor', 'Move index finger'],
  ['02', 'Click', 'Pinch thumb + index'],
  ['03', 'Scroll', 'Two fingers + vertical motion'],
  ['04', 'Zoom', 'Three fingers + vertical motion'],
]

function ClockLabel({ value }: { value: string }) {
  const time = value ? new Date(value) : null
  return <time>{time && !Number.isNaN(time.getTime()) ? time.toLocaleTimeString() : '—'}</time>
}

export default function App() {
  const [engines, setEngines] = useState<Engines>(EMPTY)
  const [gestureEnabled, setGestureEnabled] = useState(false)
  const [connected, setConnected] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [logs, setLogs] = useState<LogItem[]>([])
  const logEnd = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let disposed = false

    function connect() {
      if (disposed) return
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      ws = new WebSocket(`${protocol}//${window.location.host}/ws`)
      ws.onopen = () => {
        if (!disposed) { setConnected(true); setError('') }
      }
      ws.onmessage = (raw) => {
        try {
          const event = JSON.parse(raw.data as string) as Incoming
          if (event.type === 'snapshot') {
            setEngines(event.engines)
            setGestureEnabled(Boolean(event.gesture_enabled))
            setLogs(event.logs)
          } else if (event.type === 'status') {
            setEngines(event.engines)
            setGestureEnabled(Boolean(event.gesture_enabled))
          } else if (event.type === 'log') {
            setLogs(prev => [...prev.slice(-199), event])
          }
        } catch { /* Bad event: ignore, don't break the dashboard. */ }
      }
      ws.onclose = () => {
        if (!disposed) { setConnected(false); retry = setTimeout(connect, 1600) }
      }
      ws.onerror = () => { ws?.close() }
    }
    connect()
    return () => {
      disposed = true
      if (retry) clearTimeout(retry)
      ws?.close()
    }
  }, [])

  useEffect(() => { logEnd.current?.scrollIntoView({ block: 'nearest' }) }, [logs.length])

  async function send(path: string, payload?: { enabled: boolean }) {
    if (!connected || busy) return
    setBusy(true)
    setError('')
    try {
      const res = await fetch(`/api${path}`, { method: 'POST',
        headers: payload ? { 'Content-Type': 'application/json' } : undefined,
        body: payload ? JSON.stringify(payload) : undefined,
      })
      const body = (await res.json()) as {
        engines?: Engines;
        gesture_enabled?: boolean;
        errors?: string[];
        detail?: string
      }
      if (!res.ok) throw new Error(body.detail || `Request failed: ${res.status}`)
      if (body.engines) setEngines(body.engines)
      if (typeof body.gesture_enabled === 'boolean') setGestureEnabled(body.gesture_enabled)
      if (body.errors?.length) setError(body.errors.join(' · '))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot contact the backend')
    } finally {
      setBusy(false)
    }
  }

  const runningCount = Number(engines.gesture.running) + Number(engines.voice.running)

  return (
    <div className="app-shell">
      <div className="ambient ambient-a" /><div className="ambient ambient-b" />
      <header className="topbar">
        <div className="brand"><span className="brand-icon">✋</span><span>GestureVoice<span className="brand-highlight"> AI</span></span></div>
        <div className="header-right">
          <span className="version-pill">CONTROL CENTER / V2</span>
          <span className={`connection-pill ${connected ? 'online' : 'offline'}`}><i /> {connected ? 'Backend connected' : 'Backend disconnected'}</span>
        </div>
      </header>

      <main className="main-layout">
        <section className="hero">
          <div><div className="eyebrow"><span className="line" /> YOUR DESKTOP, REIMAGINED</div>
            <h1>Control without <span>touch.</span></h1>
            <p>One place to run your AI-powered gesture and voice controls. Start both engines, follow their live output, and manage your laptop hands-free.</p>
          </div>
          <div className="hero-stats">
            <span>ACTIVE ENGINES</span>
            <strong>{runningCount}<small> / 2</small></strong>
            <div className="progress"><span style={{ width: `${runningCount * 50}%` }} /></div>
          </div>
        </section>

        <section className="command-row">
          <div><h2>System controls</h2><p>Launch or stop either engine independently.</p></div>
          <div className="toolbar">
            <button className="primary" disabled={!connected || busy} onClick={() => send('/start-all')}>▶ &nbsp; Start both</button>
            <button className="danger" disabled={!connected || busy} onClick={() => send('/stop-all')}>■ &nbsp; Stop all</button>
          </div>
        </section>
        {error && <div role="alert" className="error-box">⚠ &nbsp; {error}</div>}

        <section className="cards">
          <article className="engine-card">
            <div className="card-top"><div className="engine-icon gesture">✋</div><div className={`engine-state ${engines.gesture.running ? 'active' : ''}`}><i /> {engines.gesture.running ? 'PROCESS RUNNING' : 'STOPPED'}</div></div>
            <h3>Hand Gesture Engine</h3><p>Webcam · MediaPipe · Gesture detection</p>
            <div className="preview camera-preview">
              {engines.gesture.running ? (
                <img src="/api/camera/stream" alt="Live hand-tracking camera from your laptop" />
              ) : (
                <div className="camera-placeholder"><div className="preview-icon">◎</div>
                  <strong>Camera offline</strong><span>Start gesture tracking to view your hand live.</span></div>
              )}
            </div>
            <p className="camera-note">{engines.gesture.running
              ? (gestureEnabled ? '🟢 Cursor control ON — Move your index finger.' : '⏸ Cursor control PAUSED — Enable when ready.')
              : 'Your webcam stays on this PC. Camera preview only runs while gesture engine is active.'}</p>
            <div className="card-actions">
              <button disabled={!connected || busy || engines.gesture.running} onClick={() => send('/engines/gesture/start')}>▶ Start gesture</button>
              <button className="secondary" disabled={!connected || busy || !engines.gesture.running} onClick={() => send('/engines/gesture/stop')}>■ Stop</button>
            </div>
            <button className="toggle-gesture" disabled={!connected || busy || !engines.gesture.running}
              onClick={() => send('/gesture/control', { enabled: !gestureEnabled })}>
              {gestureEnabled ? '⏸ Pause cursor control' : '☝ Enable cursor control'}
            </button>
          </article>

          <article className="engine-card">
            <div className="card-top"><div className="engine-icon voice">🎤</div><div className={`engine-state ${engines.voice.running ? 'active' : ''}`}><i /> {engines.voice.running ? 'PROCESS RUNNING' : 'STOPPED'}</div></div>
            <h3>Voice Command Engine</h3><p>Microphone · Offline Vosk · Windows actions</p>
            <div className="preview voice-preview">
              <div className="signal-bars"><i /><i /><i /><i /><i /><i /><i /></div>
              <div><strong>{engines.voice.running ? 'Voice process is running' : 'Voice engine is idle'}</strong><span>Recognized phrases and actions appear in the live activity panel below.</span></div>
            </div>
            <div className="card-actions">
              <button disabled={!connected || busy || engines.voice.running} onClick={() => send('/engines/voice/start')}>▶ Start voice</button>
              <button className="secondary" disabled={!connected || busy || !engines.voice.running} onClick={() => send('/engines/voice/stop')}>■ Stop</button>
            </div>
          </article>
        </section>

        <section className="lower-grid">
          <article className="panel guide-panel">
            <div className="panel-title"><h3>Gesture guide</h3><span>QUICK REFERENCE</span></div>
            <div className="guide-list">{shortcuts.map(([number, name, description]) => (
              <div className="guide-item" key={number}><span className="number">{number}</span><strong>{name}</strong><span>{description}</span></div>
            ))}</div>
            <div className="tip"><b>Tip</b> Keep your hand visible to the webcam for reliable tracking.</div>
          </article>
          <article className="panel activity-panel">
            <div className="panel-title"><h3>Live activity</h3><span className="live-tag"><i /> {connected ? 'LIVE' : 'OFFLINE'}</span></div>
            <div className="logs" aria-label="Backend log messages">
              {logs.length === 0 && <div className="log-empty">No events yet. Start an engine to see activity.</div>}
              {logs.map((log, i) => (
                <div className="log-line" key={`${log.timestamp}-${i}`}>
                  <span className="log-time"><ClockLabel value={log.timestamp} /></span>
                  <span className={`log-source ${log.source}`}>{log.source}</span>
                  <span className="log-message">{log.message}</span>
                </div>
              ))}
              <div ref={logEnd} />
            </div>
            <div className="log-footer"><span>Recent events · Last 200 lines</span><button onClick={() => setLogs([])}>Clear view</button></div>
          </article>
        </section>
        <footer className="footer"><span>GestureVoice AI · Hackathon prototype</span><span>Local-only API · Your webcam and mic stay on your laptop</span></footer>
      </main>
    </div>
  )
}
