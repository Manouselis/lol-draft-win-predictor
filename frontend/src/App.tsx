import { useEffect, useRef, useState } from 'react'
import { Activity, ArrowDownLeft, ArrowRight, ArrowUpRight, BarChart3, Check, ChevronDown, CircleHelp, Database, Download, Eye, FlaskConical, GitBranch, LockKeyhole, Radio, RefreshCw, Search, Settings2, ShieldCheck, Swords, Upload, X } from 'lucide-react'
import type { AppState, Champion, Draft, History, Pick, Settings } from './types'
import { changePick, chartPoints } from './draft'

const roles = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']
const roleNames: Record<string, string> = { TOP: 'Top', JUNGLE: 'Jungle', MIDDLE: 'Mid', BOTTOM: 'Bot', UTILITY: 'Support' }
const number = (n: number) => n.toLocaleString('en-GB')
const percent = (n: number | null | undefined) => n == null ? '—' : `${(n * 100).toFixed(1)}%`
const date = (ts: number | null | undefined) => ts ? new Date(ts * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'Not yet'

async function api<T = AppState>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, { method, ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the draft or settings and try again.')
  return result
}

function Portrait({ champion, size = '' }: { champion?: Champion; size?: string }) {
  return <div className={'portrait ' + size}>{champion ? <img src={champion.portrait} alt="" loading="lazy" onError={e => { e.currentTarget.style.display = 'none' }} /> : <Swords size={21} />}</div>
}

function DraftChart({ history }: { history: History[] }) {
  const points = chartPoints(history)
  return <div className="chart-wrap"><svg viewBox="0 0 620 144" role="img" aria-label="Prediction progression during this draft">
    {[.25, .5, .75].map(p => <g key={p}><line x1="24" x2="596" y1={16 + (1 - p) * 88} y2={16 + (1 - p) * 88} stroke="#252d3d" strokeDasharray="3 5" /><text x="0" y={20 + (1 - p) * 88}>{p * 100}</text></g>)}
    {points ? <><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop stopColor="#a4f2d0" stopOpacity=".16"/><stop offset="1" stopColor="#a4f2d0" stopOpacity="0"/></linearGradient></defs><polygon points={`24,120 ${points} 596,120`} fill="url(#chart-fill)"/><polyline points={points} stroke="#a4f2d0" fill="none" strokeWidth="2.5" strokeLinejoin="round" /></> : <text x="310" y="67" textAnchor="middle" className="chart-empty">Your draft story will appear here</text>}
    <text x="24" y="140">DRAFT START</text><text x="596" y="140" textAnchor="end">LATEST UPDATE</text>
  </svg></div>
}

export default function App() {
  const [state, setState] = useState<AppState | null>(null)
  const [champions, setChampions] = useState<Champion[]>([])
  const [version, setVersion] = useState<string | null>(null)
  const [page, setPage] = useState('draft')
  const [error, setError] = useState('')
  const [online, setOnline] = useState(false)
  const [picker, setPicker] = useState<{ team: 'allies' | 'enemies'; index: number } | null>(null)
  const [query, setQuery] = useState('')
  const [chosenState, setChosenState] = useState<'hover' | 'locked'>('locked')
  const [chosenRole, setChosenRole] = useState('')
  const [draftBusy, setDraftBusy] = useState(false)
  const [settings, setSettings] = useState<Settings | null>(null)
  const [patches, setPatches] = useState('')
  const [replayStep, setReplayStep] = useState(0)
  const fileInput = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)
  const settingsInitialized = useRef(false)
  const champion = (id: number) => champions.find(c => c.id === id)
  const championName = (id: number) => champion(id)?.name || `Champion ${id}`

  useEffect(() => {
    const source = new EventSource('/api/events')
    source.onmessage = event => {
      const next: AppState = JSON.parse(event.data)
      setState(next); setOnline(true)
      setSettings(current => current || next.settings)
      if (!settingsInitialized.current) {
        setPatches(next.settings.patches.join(', ')); settingsInitialized.current = true
      }
    }
    source.onerror = () => setOnline(false)
    api<{ champions: Champion[]; version: string | null }>('/champions').then(data => { setChampions(data.champions); setVersion(data.version) }).catch(e => setError(e.message))
    return () => source.close()
  }, [])
  useEffect(() => {
    if (!picker) return
    const listener = (event: KeyboardEvent) => { if (event.key === 'Escape') setPicker(null) }
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [picker])

  async function action(path: string, method = 'POST', body?: unknown) {
    try { setError(''); const result = await api<Partial<AppState>>(path, method, body); if (result.draft) setState(result as AppState) }
    catch (e) { setError((e as Error).message) }
  }
  async function updateDraft(draft: Draft) {
    if (draftBusy) return
    setDraftBusy(true)
    try { setError(''); setState(await api('/draft', 'POST', draft)) }
    catch (e) { setError((e as Error).message) }
    finally { setDraftBusy(false) }
  }
  function openPicker(team: 'allies' | 'enemies', index: number) {
    if (!state || state.mode === 'live' || draftBusy) return
    const old = state.draft[team][index]
    setPicker({ team, index }); setQuery(''); setChosenState(old.state === 'hover' ? 'hover' : 'locked'); setChosenRole(old.role)
  }
  function select(id: number) {
    if (!state || !picker) return
    void updateDraft(changePick(state.draft, picker.team, picker.index, { champion_id: id, state: id ? chosenState : 'unknown', role: chosenRole }))
    setPicker(null)
  }
  async function importFile(file?: File) {
    if (!file) return
    setImporting(true)
    try {
      const form = new FormData(); form.append('file', file)
      const response = await fetch('/api/import', { method: 'POST', body: form })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail)
      setError('')
    } catch (e) { setError((e as Error).message) }
    finally { setImporting(false); if (fileInput.current) fileInput.current.value = '' }
  }
  async function saveSettings() {
    if (!settings) return
    await action('/settings', 'PUT', { ...settings, patches: patches.split(',').map(p => p.trim()).filter(Boolean) })
  }
  function teamColumn(team: 'allies' | 'enemies') {
    if (!state) return null
    const ours = team === 'allies'
    return <section className={'team-column ' + (ours ? 'ours' : 'theirs')} aria-label={ours ? 'Your team' : 'Enemy team'}>
      <div className="team-heading"><span className="team-line"/><h2>{ours ? 'Your team' : 'Enemy team'}</h2><span className="count-pill">{state.draft[team].filter(p => p.state === 'locked').length} / 5</span></div>
      <div className="slots">{state.draft[team].map((pick: Pick, index: number) => <button className={'slot ' + pick.state} key={index} onClick={() => openPicker(team, index)} disabled={state.mode === 'live' || draftBusy} aria-label={`${ours ? 'Your' : 'Enemy'} slot ${index + 1}: ${pick.champion_id ? championName(pick.champion_id) : 'Unknown'}`}>
        <Portrait champion={champion(pick.champion_id)} />
        <span className="slot-copy"><strong>{pick.champion_id ? championName(pick.champion_id) : 'Unknown champion'}</strong><small>{pick.role ? roleNames[pick.role] : 'Role unknown'}</small></span>
        <span className="pick-state">{pick.state === 'locked' ? <LockKeyhole size={13}/> : pick.state === 'hover' ? <Eye size={14}/> : <span className="slot-index">0{index + 1}</span>}</span>
        {pick.state !== 'unknown' && <span className={'state-label ' + pick.state}>{pick.state === 'hover' ? 'HOVER' : 'LOCKED'}</span>}
      </button>)}</div>
      <div className="team-note">{ours ? <><span className="dot mint"/> Visible allies · hovers stay tentative</> : <><span className="dot coral"/> Hidden enemy picks stay unknown</>}</div>
    </section>
  }

  const p = state?.prediction
  const dataset = state?.dataset
  const collectionRunning = state?.collection?.status === 'running'
  const jobRunning = state?.job.status === 'running'
  const trainingRunning = state?.training?.status === 'running'
  const trainingCount = state?.dataset.training_matches ?? 0
  const trainingMessage = state?.training?.message || (state?.model ? 'Last trained ' + date(state.model.trained_at) : 'Waiting for enough recent historical matches.')
  const progress = state ? Math.min(100, state.dataset.matches / state.settings.target_matches * 100) : 0
  const patchOptions = [...new Set([version?.split('.').slice(0, 2).join('.'), ...Object.keys(state?.dataset.patches || {})].filter((p): p is string => !!p))].sort((a, b) => b.localeCompare(a, undefined, { numeric: true }))
  const known = state?.draft.allies.concat(state.draft.enemies).filter(p => p.champion_id).length || 0
  const latest = state?.history[state.history.length - 1]

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e => { e.preventDefault(); setPage('draft') }}><span className="brand-mark"><GitBranch size={23}/></span><span>LEAGUE<span className="brand-sub">DRAFT LAB</span></span></a>
      <div className="workspace-label">YOUR WORKSPACE</div>
      <nav aria-label="Main navigation">{[{ id: 'draft', name: 'Draft analysis', icon: Swords }, { id: 'data', name: 'Dataset & model', icon: Database }, { id: 'settings', name: 'Settings', icon: Settings2 }].map(item => <button className={page === item.id ? 'nav-item active' : 'nav-item'} onClick={() => setPage(item.id)} key={item.id}><item.icon size={18}/>{item.name}{page === item.id && <span className="nav-active-dot"/>}</button>)}</nav>
      <div className="sidebar-bottom"><div className="local-badge"><ShieldCheck size={16}/><span>LOCAL BY DESIGN</span></div><p>Your drafts stay on your machine.<br/>No player scouting. No game control.</p><button className="help-link" onClick={() => setPage('about')}><CircleHelp size={16}/>How the estimates work<ArrowUpRight size={14}/></button><div className="build-tag"><span className="dot mint"/> Research build <span>v0.1.0</span></div></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb">Workspace <span>/</span> <strong>{page === 'draft' ? 'Draft analysis' : page === 'data' ? 'Dataset & model' : page === 'about' ? 'About this model' : 'Settings'}</strong></div><div className="top-status"><span className={'dot ' + (online ? 'mint' : 'coral')}/>{online ? 'Local service online' : 'Connecting to local service'}<span className="top-divider"/><span className="region-pill">{state?.settings.region || 'EUW1'}</span></div></header>
      <main>
        {error && <div className="alert" role="alert"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}><X size={16}/></button></div>}
        {!state ? <div className="loading"><RefreshCw className="spin"/><h1>Opening your draft workspace</h1><p>Waiting for the local Python service…</p></div> : <>
          {page === 'draft' && <>
            <div className="page-heading"><div><div className="eyebrow"><span className="tiny-line"/>COMPOSITION INTELLIGENCE</div><h1>Every pick changes the picture<span>.</span></h1><p>Explore your visible draft with a model trained on recent matches.</p></div><button className="button secondary small" onClick={() => { setReplayStep(0); void action('/draft/reset') }} disabled={state.mode === 'live' || draftBusy}><RefreshCw size={15}/>New draft</button></div>
            <div className="draft-toolbar"><div className="segmented" aria-label="Draft mode"><button className={state.mode === 'manual' ? 'selected' : ''} onClick={() => action('/mode', 'POST', { mode: 'manual' })}><FlaskConical size={15}/>Manual analysis</button><button className={state.mode === 'live' ? 'selected' : ''} onClick={() => action('/mode', 'POST', { mode: 'live' })} title={state.integration.message}><Radio size={15}/>League client{!state.integration.live_enabled && <LockKeyhole size={12}/>}</button></div><div className="draft-controls"><label>Side<select aria-label="Your team side" disabled={state.mode === 'live'} value={state.draft.side} onChange={e => updateDraft({ ...state.draft, side: e.target.value as Draft['side'] })}><option value="blue">Blue side</option><option value="red">Red side</option><option value="unknown">Unknown</option></select></label><label>Patch<select aria-label="Analysis patch" disabled={state.mode === 'live'} value={state.draft.patch} onChange={e => updateDraft({ ...state.draft, patch: e.target.value })}><option value="">Recent mix</option>{patchOptions.map(patch => <option key={patch} value={patch}>{patch}</option>)}</select></label><span className="subtle">{state.settings.queue === 420 ? 'Ranked solo / duo' : 'Ranked flex'}</span></div></div>
            <div className="draft-meta"><span><Activity size={14}/>{state.mode === 'replay' ? 'SYNTHETIC DRAFT FIXTURE' : state.mode === 'manual' ? 'MANUAL MODE' : 'LIVE · READ ONLY'}</span><span>{known} of 10 champions visible</span><span className="integration-status">{state.integration.client_detected ? 'League detected · review required for live mode' : state.integration.status === 'connected' ? 'League connected' : 'League integration disabled'}</span></div>
            <div className="draft-grid">{teamColumn('allies')}
              <section className={'prediction-card ' + (p?.ready ? 'is-ready' : '')} aria-label="Win probability"><div className="prediction-top"><span>ESTIMATED WIN PROBABILITY</span><span className="mini-chip">{p?.tentative ? 'TENTATIVE' : 'YOUR TEAM'}</span></div>
                <div className="probability-orbit"><div className="orbit-grid"/><svg viewBox="0 0 260 180" aria-hidden="true"><path d="M36 143 A108 108 0 1 1 224 143" stroke="#242d3e" strokeWidth="5" fill="none" pathLength="100" strokeLinecap="round"/>{p?.ready && <path d="M36 143 A108 108 0 1 1 224 143" stroke="#a4f2d0" strokeWidth="5" fill="none" pathLength="100" strokeDasharray={`${(p.probability || 0) * 100} 100`} strokeLinecap="round"/>}</svg><div className="probability-number" aria-live="polite">{p?.ready ? <>{((p.probability || 0) * 100).toFixed(1)}<span>%</span></> : <span className="empty-estimate">—</span>}</div><div className="probability-label">{p?.ready ? (p.tentative ? 'Including visible hovers' : 'Based on confirmed picks') : 'Model not ready'}</div></div>
                {p?.ready ? <><div className="probability-meter"><span style={{ width: `${(p.probability || 0) * 100}%` }}/></div><div className="meter-labels"><span>Your team</span><span>Enemy team</span></div><div className="estimate-details"><div title={p.interval_label}><span>Calibration band</span><strong>{p.interval ? `${percent(p.interval[0])} – ${percent(p.interval[1])}` : 'Not available'}</strong></div><div><span>Confirmed estimate</span><strong>{percent(state.confirmed.probability)}</strong></div><div><span>After latest change</span><strong className="mint-text">{latest?.change == null ? 'Baseline' : `${latest.change > 0 ? '+' : ''}${(latest.change * 100).toFixed(2)} pp`}</strong></div></div><div className="confidence-chip"><ShieldCheck size={14}/>{p.confidence === 'supported' ? 'Held-out calibration available' : 'Limited evidence · interpret cautiously'}</div></> : <div className="not-ready"><p>{p?.reason}</p><div className="readiness-track"><span style={{ width: `${Math.min(100, trainingCount / state.minimum_matches * 100)}%` }}/></div><div className="readiness-label"><span>{number(trainingCount)} trainable matches</span><span>{number(state.minimum_matches)} minimum</span></div><button className="button primary" onClick={() => setPage('data')}>Prepare historical model<ArrowRight size={15}/></button></div>}
                <div className="prediction-foot"><Database size={12}/>{p?.version ? `Model ${p.version.slice(0, 8)} · ${number(p.dataset_matches || 0)} matches` : 'Real historical data required · last 30 days only'}</div>
              </section>{teamColumn('enemies')}
            </div>
            {p?.ready && state.model && <p className="model-patch-note">Model fit patches: {Object.keys(state.model.patches).join(", ")} · analysis: {state.draft.patch || "recent patch mixture"}</p>}
            {p?.validation_warning && <div className="warning-note">This model did not consistently outperform the historical baseline on held-out matches. Treat its draft estimates as exploratory.</div>}
            <div className="analysis-grid"><section className="panel progression"><div className="panel-header"><div><h2><BarChart3 size={17}/>Draft progression</h2><p>How your estimate evolves as visible picks change</p></div><span className="text-badge">{state.history.length} EVENTS</span></div><DraftChart history={state.history}/><div className="history-strip">{state.history.slice(-6).map((h, i) => <span className="history-item" key={`${h.time}-${i}`}><span className={'dot ' + (h.tentative ? 'amber' : 'mint')}/>{h.known}/10 <strong>{percent(h.probability)}</strong>{h.change != null && <small>{h.change > 0 ? '+' : ''}{(h.change * 100).toFixed(1)} pp</small>}</span>)}</div></section>
              <section className="panel evidence"><div className="panel-header"><div><h2><Activity size={17}/>Composition signals</h2><p>Associations supported by historical samples</p></div></div>{p?.effects?.length ? <div className="effects">{p.effects.map(effect => <div className="effect" key={effect.champion_id}><Portrait champion={champion(effect.champion_id)} size="tiny"/><span><strong>{championName(effect.champion_id)}</strong><small>{number(effect.training_matches)} training matches</small></span><b className={effect.change >= 0 ? 'mint-text' : 'coral-text'}>{effect.change >= 0 ? <ArrowUpRight size={16}/> : <ArrowDownLeft size={16}/>}{Math.abs(effect.change * 100).toFixed(1)} pp</b></div>)}<p className="fine-print">Change when that champion is omitted. Associations are not causal effects.</p></div> : <div className="evidence-empty"><span className="empty-icon"><GitBranch size={22}/></span><strong>Let the data speak first.</strong><p>Supported matchup and synergy signals appear after a historical model is trained.</p></div>}</section></div>
            {!!p?.statistics?.length && <section className="panel"><div className="panel-header"><h2>Historical combinations</h2><span className="subtle">Descriptive training cohort · minimum 100 occurrences</span></div><div className="statistics-grid">{p.statistics.map((s, i) => <div className="stat-combo" key={i}><span className="eyebrow">{s.kind === 'synergy' ? 'ALLIED PAIR' : 'HEAD TO HEAD'}</span><strong>{s.champions.map(championName).join(s.kind === 'synergy' ? ' + ' : ' vs ')}</strong><span>{percent(s.win_rate)} wins for {s.kind === 'synergy' ? 'this pair' : championName(s.champions[0])} · {number(s.matches)} matches</span></div>)}</div></section>}
            <div className="data-ribbon"><span className="ribbon-icon"><Database size={18}/></span><div><strong>{number(dataset!.matches)} recent matches in your dataset</strong><p>{Object.keys(dataset!.patches).length ? `Patches ${Object.keys(dataset!.patches).join(', ')} · ` : ''}Strict 30-day window · last refresh {date(dataset!.last_refresh)}</p></div><button onClick={() => setPage('data')}>Manage dataset<ArrowRight size={16}/></button></div>
          </>}
          {page === 'data' && <>
            <div className="page-heading"><div><div className="eyebrow"><span className="tiny-line"/>THE FOUNDATION OF EVERY ESTIMATE</div><h1>Real matches. Recent patches<span>.</span></h1><p>Collect, inspect, and train on actual ranked matches from the last 30 days.</p></div><span className="policy-chip"><ShieldCheck size={15}/>30-day limit enforced</span></div>
            <div className="metrics-grid"><div className="metric-card"><span>ELIGIBLE MATCHES</span><strong>{number(dataset!.matches)}</strong><small>Unique · {state.settings.region} · queue {state.settings.queue}</small></div><div className="metric-card"><span>PATCH COVERAGE</span><strong>{Object.keys(dataset!.patches).length}</strong><small>{Object.keys(dataset!.patches).join(' / ') || 'Waiting for historical matches'}</small></div><div className="metric-card"><span>MODEL STATUS</span><strong className="status-text">{trainingRunning ? 'Training' : p?.ready ? 'Trained' : 'Not ready'}</strong><small>{state.model ? `Version ${state.model.version}` : `${number(state.minimum_matches)} match readiness floor`}</small></div><div className="metric-card"><span>LAST REFRESH</span><strong className="status-text">{dataset!.last_refresh ? new Date(dataset!.last_refresh * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}</strong><small>{date(dataset!.last_refresh)}</small></div></div>
            <section className="panel collection-panel"><div className="panel-header"><div><h2><Download size={19}/>Historical data collection</h2><p>Official Riot Match-V5 · {state.settings.tiers.join(', ')} ranked seed tiers</p></div><span className={'key-badge ' + (state.api_key_configured ? 'configured' : '')}>{state.api_key_configured ? <><Check size={14}/>API key configured</> : 'API key needed in .env'}</span></div><div className="collection-progress-heading"><strong>{number(dataset!.matches)} <span>/ {number(state.settings.target_matches)} target matches</span></strong><b>{progress.toFixed(1)}%</b></div><div className="big-progress"><span style={{ width: `${progress}%` }}/></div><p className="collection-status" aria-live="polite">{collectionRunning && <RefreshCw size={14} className="spin"/>}{state.collection?.message || 'Ready to collect. Downloads are resumable and deduplicated.'}</p><div className="button-row"><button className="button primary" disabled={jobRunning || collectionRunning} onClick={() => action('/collect')}><Download size={16}/>{dataset!.matches ? 'Resume collection' : 'Start collection'}</button><button className="button secondary" disabled={jobRunning || importing} onClick={() => fileInput.current?.click()}><Upload size={16}/>{importing ? 'Uploading…' : 'Import Match-V5 data'}</button>{(collectionRunning || (state.job.kind === 'collect' && jobRunning)) && <button className="button secondary" onClick={() => action('/jobs/stop')}>Stop & save progress</button>}<input ref={fileInput} type="file" accept=".json,.jsonl,.ndjson" hidden onChange={e => importFile(e.target.files?.[0])}/></div><p className="fine-print">100,000 match requests take at least 33 hours at a development key's 100-per-two-minute limit. Keys expire; update the local .env file and resume. Seed tiers describe current ladder cohorts, not verified rank at match time.</p></section>
            <div className="analysis-grid"><section className="panel"><div className="panel-header"><div><h2><GitBranch size={18}/>Train & validate</h2><p>Chronological fit / calibration / test split · 90 / 5 / 5</p></div></div><div className="training-copy"><div className="training-readiness"><span>READY FOR TRAINING · LAST 29 DAYS</span><strong>{number(trainingCount)} <small>/ {number(state.minimum_matches)}</small></strong><p>{number(state.dataset.aging_matches || 0)} additional matches are in the 30-day analysis window and outside the training safety margin.</p></div><p>Eight masked versions per training match teach the model to work with incomplete drafts. Each real match retains one match's total statistical weight.</p><p>Champion pairs, matchups, roles, patch effects, and side are learned from outcomes. Newer matches receive more weight.</p><div className="training-job">{trainingRunning && <RefreshCw size={15} className="spin"/>}{trainingMessage}</div><button className="button primary" disabled={jobRunning || trainingRunning || trainingCount < state.minimum_matches} onClick={() => action('/train')}><FlaskConical size={16}/>Train on recent matches</button><p className="fine-print">Training uses a 29-day subset to stay within the 30-day requirement for at least one day. Expired model artifacts are rejected automatically.</p></div></section><section className="panel"><div className="panel-header"><h2>Patch distribution</h2><span className="text-badge">RECENT ONLY</span></div><div className="patch-list">{Object.entries(dataset!.patches).map(([patch, n]) => <div className="patch-item" key={patch}><span>Patch {patch}</span><strong>{number(n)}</strong><div><span style={{ width: `${n / Math.max(1, dataset!.matches) * 100}%` }}/></div></div>)}{!Object.keys(dataset!.patches).length && <p className="subtle">Patch coverage appears as real matches arrive.</p>}</div><div className="dataset-dates"><span>Oldest eligible<strong>{date(dataset!.oldest)}</strong></span><span>Newest eligible<strong>{date(dataset!.newest)}</strong></span><span>Pending download IDs<strong>{number(dataset!.pending_downloads)}</strong></span></div></section></div>
            {state.model && <section className="panel evaluation"><div className="panel-header"><div><h2>Held-out evaluation</h2><p>Lower scores are better. Comparison uses the same test matches for every reveal count.</p></div><span className="text-badge">{number(state.model.report.split.test)} TEST MATCHES</span></div><div className="table-scroll"><table><thead><tr><th>Visible champions</th><th>Model Brier</th><th>Baseline Brier</th><th>Model log loss</th><th>Baseline log loss</th><th>Calibration ECE</th></tr></thead><tbody>{Object.entries(state.model.report.groups).map(([n, g]) => <tr key={n}><td>{n} / 10 {n === '0' ? '· baseline' : n === '10' ? '· complete' : '· partial'}</td><td>{g.model.brier.toFixed(4)}</td><td>{g.baseline.brier.toFixed(4)}</td><td>{g.model.log_loss.toFixed(4)}</td><td>{g.baseline.log_loss.toFixed(4)}</td><td>{g.model.ece.toFixed(4)}</td></tr>)}</tbody></table></div>{state.model.report.validation_warning && <p className="warning-note">This model does not consistently outperform the baseline. More data or model changes are needed before treating it as reliable.</p>}</section>}
            {state.job.kind && <div className={'job-banner ' + state.job.status}><Activity size={16}/><strong>{state.job.kind}</strong><span>{state.job.message}</span>{state.job.status === 'complete' && state.job.result != null && <details><summary>Details</summary><pre>{JSON.stringify(state.job.result, null, 2)}</pre></details>}</div>}
          </>}
          {page === 'settings' && settings && <>
            <div className="page-heading"><div><div className="eyebrow"><span className="tiny-line"/>MAKE IT YOUR WORKSPACE</div><h1>Analysis settings<span>.</span></h1><p>Set the population your historical model should represent.</p></div></div>
            <section className="panel settings-panel"><div className="panel-header"><h2>Historical data scope</h2><span className="text-badge">LOCAL CONFIGURATION</span></div><div className="form-grid"><label>Riot platform<select value={settings.region} onChange={e => setSettings({ ...settings, region: e.target.value })}>{['EUW1', 'EUN1', 'NA1', 'KR', 'JP1', 'BR1', 'LA1', 'LA2', 'TR1', 'RU', 'OC1', 'SG2', 'TW2', 'VN2', 'PH2', 'TH2'].map(r => <option key={r}>{r}</option>)}</select><small>Changing platform requires training a matching model.</small></label><label>Ranked queue<select value={settings.queue} onChange={e => setSettings({ ...settings, queue: Number(e.target.value) })}><option value={420}>Ranked solo / duo · 420</option><option value={440}>Ranked flex · 440</option></select><small>Summoner's Rift ranked matches only.</small></label><label>Patch filter<input placeholder="All recent patches, e.g. 16.20" value={patches} onChange={e => setPatches(e.target.value)}/><small>Optional comma-separated patch versions within 30 days.</small></label><label>Collection target<input type="number" min={50000} max={1000000} step={10000} value={settings.target_matches} onChange={e => setSettings({ ...settings, target_matches: Number(e.target.value) })}/><small>50,000 minimum; the default target is 100,000 unique matches.</small></label></div><div className="tier-field"><strong>Ranked seed tiers</strong><div className="tier-chips">{['IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM', 'EMERALD', 'DIAMOND', 'MASTER', 'GRANDMASTER', 'CHALLENGER'].map(tier => <button className={settings.tiers.includes(tier) ? 'selected' : ''} key={tier} onClick={() => setSettings({ ...settings, tiers: settings.tiers.includes(tier) ? settings.tiers.filter(t => t !== tier) : [...settings.tiers, tier] })}>{tier}</button>)}</div></div><div className="settings-footer"><p><ShieldCheck size={16}/>{collectionRunning || trainingRunning ? 'Stop collection and wait for training before changing scope.' : 'The 30-day maximum cannot be extended.'}</p><button className="button primary" disabled={jobRunning || collectionRunning || trainingRunning} onClick={saveSettings}><Check size={16}/>Save data settings</button></div></section>
            <section className="panel settings-panel"><div className="panel-header"><div><h2>League client integration</h2><p>{state.integration.message}</p></div><span className="key-badge">{state.integration.status}</span></div><div className="integration-copy"><ShieldCheck size={24}/><div><strong>Read-only integration requires Riot review.</strong><p>Riot's League Client API is unsupported. This live probability use case needs review before enabling it. The adapter reads only visible champion-select data; it never selects champions or reads player identities.</p><p>After Riot permits this exact use case, set LOL_RIOT_LIVE_APPROVED=true and LOL_LCU_ENABLED=true in your local .env and restart. Approval cannot be granted by this app.</p></div></div><div className="button-row"><button className="button secondary" onClick={() => { setReplayStep(0); void action('/replay/0'); setPage('draft') }}><FlaskConical size={16}/>Test synthetic draft replay</button><button className="button secondary" onClick={async () => { try { const data = await api<{ champions: Champion[]; version: string }>('/champions/refresh', 'POST'); setChampions(data.champions); setVersion(data.version) } catch (e) { setError((e as Error).message) } }}><RefreshCw size={16}/>Refresh champion catalog</button></div><p className="fine-print">Champion catalog: Data Dragon {version || 'unavailable'}. API keys stay in .env and are never sent to the browser.</p></section>
          </>}
          {page === 'about' && <><div className="page-heading"><div><div className="eyebrow">METHOD & LIMITATIONS</div><h1>Evidence before confidence<span>.</span></h1><p>An interpretable research model, with its uncertainty in view.</p></div></div><section className="panel about-copy"><h2>What the number means</h2><p>The estimate is a historical association between visible champion composition and match outcome in the selected ranked population. It does not account for player skill, familiarity, coordination, or what happens in game.</p><h2>Unknown means unknown</h2><p>Training masks hide randomly chosen champions in real historical matches. At inference, only visible champions enter the model. Remaining picks are statistically marginalized through this masked training objective; no champions are filled in behind the scenes. Random masks approximate draft information, not the causal process of champion selection.</p><h2>How we validate</h2><p>Distinct matches are split by time before augmentation. The first 90% fit an L2 regularized logistic model, the next 5% calibrate it, and the final 5% measure Brier score, log loss, and calibration separately for empty, partial, and complete drafts. The baseline is the recency-weighted historical blue-side win rate, not a fixed percentage.</p><h2>Recent data has limits</h2><p>Only matches in the last 30 days can be imported or used. Training reserves a one-day age margin, weights outcomes with a seven-day half-life, and learns patch-specific champion associations. Patch notes are not strength scores; patch changes are reflected through newly observed outcomes. New champions or patches without enough outcomes need more data.</p><h2>Reading the uncertainty</h2><p>The calibration band is a Wilson interval for the observed outcomes in a similar probability bin of held-out matches at a nearby reveal count. It is not a confidence interval for the outcome of your individual match. Sparse evidence and poor validation remain visible. Draft features may have very little predictive power.</p><h2>Policy and privacy</h2><p>Local drafts and credentials never leave your machine. Collection sends your developer key only to official Riot HTTPS APIs. Data Dragon serves champion assets. Only anonymized composition facts are stored. A public source repository does not mean Riot has approved the product or its deployment.</p><a href="https://developer.riotgames.com/docs/lol" target="_blank" rel="noreferrer">Read Riot's developer documentation <ArrowUpRight size={14}/></a></section></>}
          {state.mode === 'replay' && <div className="replay-bar"><FlaskConical size={17}/><strong>Synthetic draft fixture</strong><span>Step {replayStep + 1} / 7 · no synthetic match data is used for predictions</span><button className="button secondary small" disabled={replayStep >= 6} onClick={() => { const next = replayStep + 1; setReplayStep(next); void action(`/replay/${next}`) }}>Next visible change<ArrowRight size={14}/></button><button aria-label="Exit replay" onClick={() => action('/mode', 'POST', { mode: 'manual' })}><X size={17}/></button></div>}
        </>}
      </main>
      <footer><span>League Draft Lab is not endorsed by Riot Games and does not reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.</span><span>LOCAL RESEARCH TOOL</span></footer>
    </div>
    {picker && state && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setPicker(null) }}><section className="champion-modal" role="dialog" aria-modal="true" aria-labelledby="picker-title"><div className="modal-heading"><div><span className="eyebrow">{picker.team === 'allies' ? 'YOUR TEAM' : 'ENEMY TEAM'} · SLOT {picker.index + 1}</span><h2 id="picker-title">Choose a visible champion</h2></div><button aria-label="Close champion selector" onClick={() => setPicker(null)}><X size={20}/></button></div><div className="picker-options"><div className="segmented"><button className={chosenState === 'locked' ? 'selected' : ''} onClick={() => setChosenState('locked')}><LockKeyhole size={14}/>Locked</button><button className={chosenState === 'hover' ? 'selected' : ''} onClick={() => setChosenState('hover')}><Eye size={14}/>Hover</button></div><label className="role-picker">Role<select aria-label="Champion role" value={chosenRole} onChange={e => setChosenRole(e.target.value)}><option value="">Unknown</option>{roles.map(role => <option key={role} value={role}>{roleNames[role]}</option>)}</select><ChevronDown size={13}/></label></div><label className="champion-search"><Search size={18}/><input autoFocus placeholder="Search champion name or ID…" value={query} onChange={e => setQuery(e.target.value)}/><span>{champions.length}</span></label><div className="champion-results">{champions.filter(c => c.name.toLowerCase().includes(query.toLowerCase()) || String(c.id) === query).map(c => <button key={c.id} className="champion-option" onClick={() => select(c.id)}><Portrait champion={c}/><span>{c.name}</span></button>)}{!champions.length && <p>Champion catalog unavailable. Refresh it in Settings.</p>}</div><div className="modal-footer"><button onClick={() => select(0)}><X size={14}/>Keep this slot unknown</button><span>Hovers are tentative. Select only information you can see.</span></div></section></div>}
  </div>
}


