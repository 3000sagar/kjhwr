import { lazy, Suspense, useEffect, useState } from 'react'
import { getDeliveryDays, type DeliveryDay, type Mode } from './api'

const Accuracy = lazy(() => import('./pages/Accuracy'))
const DayAhead = lazy(() => import('./pages/DayAhead'))

type Page = 'day' | 'accuracy'

export default function App() {
  const [page, setPage] = useState<Page>('day')
  const [cutoff, setCutoff] = useState('09:00')
  const [mode, setMode] = useState<Mode>('raw')
  const [deliveryDays, setDeliveryDays] = useState<DeliveryDay[]>([])
  const [selectedDay, setSelectedDay] = useState('2026-01-15')
  const [dayListError, setDayListError] = useState('')

  useEffect(() => {
    let active = true
    getDeliveryDays(cutoff, mode)
      .then((days) => {
        if (!active) return
        setDeliveryDays(days)
        setDayListError('')
        if (!days.some((item) => item.delivery_date === selectedDay) && days.length > 0) {
          setSelectedDay(days[0].delivery_date)
        }
      })
      .catch((error: Error) => active && setDayListError(error.message))
    return () => { active = false }
  }, [cutoff, mode, selectedDay])

  const title = page === 'day' ? 'Day-ahead view' : 'Forecast accuracy'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><span /></div>
          <div>
            <div className="brand-title">WIND DESK</div>
            <div className="brand-subtitle">POWER OPERATIONS</div>
          </div>
        </div>
        <div className="sidebar-section-label">WORKSPACE</div>
        <nav className="side-nav" aria-label="Dashboard pages">
          <button className={page === 'day' ? 'nav-item active' : 'nav-item'} onClick={() => setPage('day')}>
            <span className="nav-glyph">◷</span><span>Day ahead</span><span className="nav-arrow">›</span>
          </button>
          <button className={page === 'accuracy' ? 'nav-item active' : 'nav-item'} onClick={() => setPage('accuracy')}>
            <span className="nav-glyph">⌁</span><span>Accuracy</span><span className="nav-arrow">›</span>
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="live-indicator"><span className="status-dot" /> PRECOMPUTED DATA</div>
          <p>January decision window<br /><strong>02 Jan — 01 Feb 2026</strong></p>
          <div className="sidebar-rule" />
          <span className="sidebar-caption">WIND GENERATION<br />DAY-AHEAD ANALYSIS</span>
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <div className="topbar-heading">
            <div className="eyebrow">WIND PORTFOLIO <span>/</span> JANUARY 2026</div>
            <h1>{title}</h1>
          </div>
          <div className="toolbar-controls">
            <label className="cutoff-control">
              <span>DECISION CUTOFF</span>
              <input aria-label="Decision cutoff" type="time" value={cutoff} onChange={(event) => setCutoff(event.target.value)} />
              <small>Europe/London</small>
            </label>
            <div className="mode-control" role="group" aria-label="Forecast adjustment mode">
              <button className={mode === 'raw' ? 'mode-option selected' : 'mode-option'} onClick={() => setMode('raw')}>Raw</button>
              <button className={mode === 'bias_corrected' ? 'mode-option selected' : 'mode-option'} onClick={() => setMode('bias_corrected')}>Bias corrected</button>
            </div>
          </div>
        </header>

        <main className="page-content">
          {dayListError && <div className="global-error" role="alert">Could not load delivery days: {dayListError}</div>}
          <Suspense fallback={<div className="loading-line"><span className="spinner" /> Loading dashboard…</div>}>
            {page === 'day'
              ? <DayAhead cutoff={cutoff} mode={mode} deliveryDays={deliveryDays} selectedDay={selectedDay} onSelectDay={setSelectedDay} />
              : <Accuracy cutoff={cutoff} mode={mode} />}
          </Suspense>
        </main>

        <footer className="page-footnote">
          <span>ONE-MONTH SAMPLE · 31 DELIVERY DAYS</span>
          <span>Actuals lookback starts 18 Dec 2025 to support trailing correction; scored window remains Jan 2–Feb 1.</span>
        </footer>
      </div>
    </div>
  )
}
