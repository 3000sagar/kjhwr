import { useEffect, useMemo, useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { getDay, getSummary, type DayData, type DeliveryDay, type Mode } from '../api'
import MetricCard from '../components/MetricCard'

interface DayAheadProps {
  cutoff: string
  mode: Mode
  deliveryDays: DeliveryDay[]
  selectedDay: string
  onSelectDay: (day: string) => void
}

const number = (value: number | null | undefined, digits = 0) =>
  value == null ? '—' : new Intl.NumberFormat('en-GB', { maximumFractionDigits: digits }).format(value)

const utcTime = (value: string) => new Intl.DateTimeFormat('en-GB', {
  timeZone: 'UTC', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
}).format(new Date(value))

function getCutoffUtc(day: string, cutoff: string): number {
  const priorDay = new Date(`${day}T00:00:00Z`)
  priorDay.setUTCDate(priorDay.getUTCDate() - 1)
  const [hours, minutes] = cutoff.split(':').map(Number)
  return Date.UTC(priorDay.getUTCFullYear(), priorDay.getUTCMonth(), priorDay.getUTCDate(), hours, minutes)
}

function forecastTiming(day: DayData, cutoff: string) {
  const publications = day.points
    .map((point) => point.publish_time)
    .filter((value): value is string => value !== null)
    .map((value) => new Date(value).getTime())
  if (publications.length === 0) return { label: 'No eligible publication', age: '—' }
  const latest = Math.max(...publications)
  const earliest = Math.min(...publications)
  const latestLabel = utcTime(new Date(latest).toISOString())
  const earliestLabel = utcTime(new Date(earliest).toISOString())
  const hours = (getCutoffUtc(day.delivery_date, cutoff) - latest) / 3_600_000
  const range = earliest === latest ? latestLabel : `${earliestLabel} — ${latestLabel} UTC`
  return { label: `${range}${earliest === latest ? ' UTC' : ''}`, age: `${number(hours, 1)} h` }
}

export default function DayAhead({ cutoff, mode, deliveryDays, selectedDay, onSelectDay }: DayAheadProps) {
  const [day, setDay] = useState<DayData | null>(null)
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof getSummary>> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    Promise.all([getDay(selectedDay, cutoff, mode), getSummary(cutoff, mode)])
      .then(([dayResult, summaryResult]) => {
        if (!active) return
        setDay(dayResult)
        setSummary(summaryResult)
        setError('')
      })
      .catch((reason: Error) => active && setError(reason.message))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [selectedDay, cutoff, mode])

  const points = useMemo(() => day?.points.map((point) => ({
    ...point,
    clock: new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', hour: '2-digit', minute: '2-digit', hour12: false })
      .format(new Date(point.start_time)),
  })) ?? [], [day])
  const timing = day ? forecastTiming(day, cutoff) : null
  const selectedLabel = new Date(`${selectedDay}T12:00:00`).toLocaleDateString('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  })

  return (
    <div className="page-stack">
      <section className="page-intro day-intro">
        <div>
          <div className="eyebrow">BUYING DESK <span>/</span> WIND SUPPLY</div>
          <h2>Day-ahead position - replay of {selectedDay}</h2>
          <p>Latest forecast available at the decision cutoff, aligned to half-hour delivery periods. Actuals are shown for evaluation only and would not be known at the decision time.</p>
        </div>
        <label className="date-picker">
          <span>DELIVERY DAY</span>
          <select value={selectedDay} onChange={(event) => onSelectDay(event.target.value)} aria-label="Delivery day">
            {deliveryDays.map((item) => <option key={item.delivery_date} value={item.delivery_date}>{item.delivery_date}</option>)}
          </select>
        </label>
      </section>

      {error && <div className="error-banner" role="alert">Could not load day-ahead data: {error}</div>}
      {loading && <div className="loading-line"><span className="spinner" /> Loading the selected forecast…</div>}
      {!loading && day && summary && (
        <>
          <section className="forecast-strip">
            <div className="forecast-strip-icon">↗</div>
            <div className="forecast-strip-copy">
              <span className="strip-label">FORECAST AS OF</span>
              <strong>{timing?.label}</strong>
              <span className="strip-date">{selectedLabel}</span>
            </div>
            <div className="strip-divider" />
            <div className="forecast-strip-copy">
              <span className="strip-label">DECISION CUTOFF</span>
              <strong>{cutoff} <small>Europe/London</small></strong>
              <span className="strip-date">Forecast age at cutoff: {timing?.age}</span>
            </div>
            <div className="strip-mode">{mode === 'raw' ? 'RAW FORECAST' : 'BIAS CORRECTED'}</div>
          </section>

          <section className="metric-grid day-metrics" aria-label="Delivery day metrics">
            <MetricCard label="Forecast energy" value={`${number(day.summary.forecast_mwh)} MWh`} detail="Across the delivery day" tone="blue" />
            <MetricCard label="Peak wind" value={`${number(day.summary.peak_forecast_mw)} MW`} detail="Maximum forecast output" />
            <MetricCard label="Minimum wind" value={`${number(day.summary.min_forecast_mw)} MW`} detail="Minimum forecast output" />
            <MetricCard label="Forecast coverage" value={`${number(day.summary.coverage * 100, 1)}%`} detail={`${day.summary.coverage === 1 ? '48 of 48' : `${day.points.filter((point) => point.forecast_mw !== null).length} of 48`} half-hours selected`} tone="green" />
          </section>

          <section className="content-grid day-chart-grid">
            <article className="panel chart-panel">
              <div className="panel-heading">
                <div><span className="eyebrow">DELIVERY PROFILE</span><h3>Wind generation forecast</h3></div>
                <div className="chart-legend"><span><i className="legend-line forecast-line" />Forecast</span><span><i className="legend-line actual-line" />Actual</span><span><i className="legend-band" />Historical error band</span></div>
              </div>
              <p className="panel-subtitle">MW by half-hour · local delivery time · band shows in-sample historical residual quantiles</p>
              <div className="chart-wrap day-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={points} margin={{ top: 12, right: 12, bottom: 2, left: 0 }}>
                    <CartesianGrid stroke="#e8edf3" vertical={false} />
                    <XAxis dataKey="clock" interval={5} tickLine={false} axisLine={false} tick={{ fill: '#8693a5', fontSize: 11 }} />
                    <YAxis width={58} tickLine={false} axisLine={false} tick={{ fill: '#8693a5', fontSize: 11 }} tickFormatter={(value: number) => `${Math.round(value / 1000)}k`} />
                    <Tooltip formatter={(value) => value == null ? '—' : `${number(Number(value))} MW`} labelFormatter={(label) => `${label} local`} />
                    <Area dataKey={(point: (typeof points)[number]) => [point.band_low_mw, point.band_high_mw]} name="Historical error band" type="monotone" fill="#b7d3f5" fillOpacity={0.35} stroke="none" connectNulls />
                    <Line dataKey="forecast_mw" name="Forecast" type="monotone" stroke="#2866d8" strokeWidth={2.6} dot={false} connectNulls />
                    <Line dataKey="actual_mw" name="Actual" type="monotone" stroke="#1c9b85" strokeWidth={1.8} dot={false} connectNulls />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </article>
            <article className="panel buffer-panel">
              <div className="buffer-icon">↓</div>
              <span className="eyebrow">PROCUREMENT BUFFER</span>
              <h3>Plan for less wind</h3>
              <p>Historical P90 over-forecast risk at the selected cutoff and mode.</p>
              <div className="buffer-number">{number(summary.buffer_p90_mw)} <span>MW</span></div>
              <div className="buffer-ci">90% day-bootstrap interval <strong>{number(summary.buffer_p90_ci_low_mw)}–{number(summary.buffer_p90_ci_high_mw)} MW</strong></div>
              <div className="buffer-callout">In 90% of half-hours, actual wind came in no more than <strong>{number(summary.buffer_p90_mw)} MW</strong> below forecast.</div>
              <div className="buffer-footer">31 delivery days · {summary.n_hourly_forecasts} hourly forecasts</div>
            </article>
          </section>

          <section className="method-strip">
            <div className="method-icon">i</div>
            <div><strong>Selection rule</strong><span>For each delivery period, use the latest wind forecast published at or before {cutoff} on the previous day.</span></div>
            <div className="method-divider" />
            <div><strong>How to read the band</strong><span>Historical error quantiles by local hour; the displayed day is part of the one-month sample.</span></div>
          </section>
        </>
      )}
    </div>
  )
}
