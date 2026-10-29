import { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { getAccuracyCharts, getSummary, type AccuracySummary, type DayMetric, type HistogramBin, type HorizonMetric, type HourMetric, type Mode } from '../api'
import MetricCard from '../components/MetricCard'

interface AccuracyProps {
  cutoff: string
  mode: Mode
}

const number = (value: number | null | undefined, digits = 0) =>
  value == null ? '—' : new Intl.NumberFormat('en-GB', { maximumFractionDigits: digits }).format(value)

function ModelSummary({ title, data, selected }: { title: string; data: AccuracySummary; selected: boolean }) {
  return (
    <article className={selected ? 'model-card model-card--selected' : 'model-card'}>
      <div className="model-card-heading">
        <div><span className="eyebrow">{title}</span><h3>{selected ? 'Selected view' : 'Comparison'}</h3></div>
        {selected && <span className="selected-pill">ACTIVE</span>}
      </div>
      <div className="model-headlines">
        <MetricCard label="Mean absolute error" value={`${number(data.mae_mw)} MW`} detail="Average absolute forecast error" tone="blue" />
        <MetricCard label="P90 over-forecast buffer" value={`${number(data.buffer_p90_mw)} MW`} detail={`90% CI · ${number(data.buffer_p90_ci_low_mw)}–${number(data.buffer_p90_ci_high_mw)} MW`} tone="amber" />
      </div>
      <div className="decomposition-row">
        <div><span>Bias</span><strong>{number(data.bias_mw)} MW</strong><small>Mean forecast − actual</small></div>
        <div className="decomp-divider" />
        <div>
          <span className="spread-label" title="Raw spread removes the sample-mean bias in hindsight and is not directly comparable to corrected spread.">Spread ⓘ</span>
          <strong>{number(data.spread_mae_mw)} MW</strong>
          <small>Mean absolute error after removing bias</small>
        </div>
        <div className="decomp-divider" />
        <div><span>Normalised MAE</span><strong>{number(data.nmae * 100, 1)}%</strong><small>MAE ÷ mean actual wind</small></div>
      </div>
      <div className="model-sample">Sample size <strong>{number(data.n_hourly_forecasts)} hourly forecasts</strong></div>
    </article>
  )
}

export default function Accuracy({ cutoff, mode }: AccuracyProps) {
  const [raw, setRaw] = useState<AccuracySummary | null>(null)
  const [corrected, setCorrected] = useState<AccuracySummary | null>(null)
  const [hours, setHours] = useState<HourMetric[]>([])
  const [days, setDays] = useState<DayMetric[]>([])
  const [horizons, setHorizons] = useState<HorizonMetric[]>([])
  const [histogram, setHistogram] = useState<HistogramBin[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setLoading(true)
    Promise.all([
      getSummary(cutoff, 'raw'),
      getSummary(cutoff, 'bias_corrected'),
      getAccuracyCharts(cutoff, mode),
    ])
      .then(([rawResult, correctedResult, charts]) => {
        if (!active) return
        setRaw(rawResult)
        setCorrected(correctedResult)
        setHours(charts.byHour)
        setDays(charts.byDay)
        setHorizons(charts.byHorizon)
        setHistogram(charts.histogram)
        setError('')
      })
      .catch((reason: Error) => active && setError(reason.message))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [cutoff, mode])

  const histogramData = useMemo(() => histogram.map((bin) => ({
    ...bin,
    center: (bin.bin_low_mw + bin.bin_high_mw) / 2,
  })), [histogram])
  const activeTitle = mode === 'raw' ? 'Raw' : 'Bias corrected'

  return (
    <div className="page-stack">
      <section className="page-intro">
        <div>
          <div className="eyebrow">MODEL REVIEW <span>/</span> DECISION WINDOW</div>
          <h2>Forecast accuracy</h2>
          <p>Separate systematic bias from the remaining spread, then compare the procurement risk.</p>
        </div>
        <div className="window-stamp"><span>ANALYSIS WINDOW</span><strong>02 Jan — 01 Feb 2026</strong><small>One month of delivery days</small></div>
      </section>

      {error && <div className="error-banner" role="alert">Could not load accuracy data: {error}</div>}
      {loading && <div className="loading-line"><span className="spinner" /> Calculating forecast accuracy…</div>}
      {!loading && raw && corrected && (
        <>
          <section className="comparison-headline">
            <div className="section-heading-row">
              <div><span className="eyebrow">HEADLINE PERFORMANCE</span><h3>Raw vs bias-corrected</h3></div>
              <span className="sample-pill">{number(raw.n_hourly_forecasts)} hourly forecasts</span>
            </div>
            <div className="model-grid">
              <ModelSummary title="Raw forecast" data={raw} selected={mode === 'raw'} />
              <ModelSummary title="Bias-corrected" data={corrected} selected={mode === 'bias_corrected'} />
            </div>
            <div className="paired-delta">
              <span>Paired improvement · raw minus corrected</span>
              <strong>MAE {number(raw.raw_minus_corrected_mae_mw)} MW <small>(90% CI {number(raw.raw_minus_corrected_mae_ci_low_mw)} to {number(raw.raw_minus_corrected_mae_ci_high_mw)})</small></strong>
              <strong>P90 buffer {number(raw.raw_minus_corrected_buffer_p90_mw)} MW <small>(90% CI {number(raw.raw_minus_corrected_buffer_p90_ci_low_mw)} to {number(raw.raw_minus_corrected_buffer_p90_ci_high_mw)})</small></strong>
            </div>
          </section>

          <section className="section-heading-row chart-section-heading">
            <div><span className="eyebrow">ERROR PROFILE</span><h3>{activeTitle} detail at {cutoff}</h3></div>
            <span className="small-caption">Charts follow the active mode toggle</span>
          </section>

          <section className="content-grid accuracy-charts">
            <article className="panel chart-panel">
              <div className="panel-heading"><div><span className="eyebrow">TIME OF DAY</span><h3>Bias and spread by hour</h3></div></div>
              <p className="panel-subtitle">MW · hourly mean error and bias-removed MAE</p>
              <div className="chart-wrap medium-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={hours} margin={{ top: 10, right: 8, bottom: 3, left: -8 }}>
                    <CartesianGrid stroke="#e8edf3" vertical={false} />
                    <XAxis dataKey="hour" tickLine={false} axisLine={false} tick={{ fill: '#8693a5', fontSize: 10 }} tickFormatter={(value: number) => String(value).padStart(2, '0')} />
                    <YAxis tickLine={false} axisLine={false} tick={{ fill: '#8693a5', fontSize: 10 }} tickFormatter={(value: number) => `${Math.round(value / 1000)}k`} />
                    <Tooltip formatter={(value) => `${number(Number(value))} MW`} labelFormatter={(label) => `Hour ${String(label).padStart(2, '0')}`} />
                    <Bar dataKey="bias_mw" name="Bias" fill="#2866d8" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="spread_mae_mw" name="Spread" fill="#a9bfdc" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </article>

            <article className="panel chart-panel">
              <div className="panel-heading"><div><span className="eyebrow">FORECAST LEAD</span><h3>Error by horizon</h3></div></div>
              <p className="panel-subtitle">MAE by forecast lead-time bucket · negative horizons excluded</p>
              <div className="chart-wrap medium-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={horizons} margin={{ top: 10, right: 8, bottom: 3, left: -8 }}>
                    <CartesianGrid stroke="#e8edf3" vertical={false} />
                    <XAxis dataKey="horizon_bucket" interval={0} angle={-32} textAnchor="end" height={52} tickLine={false} axisLine={false} tick={{ fill: '#8693a5', fontSize: 9 }} />
                    <YAxis tickLine={false} axisLine={false} tick={{ fill: '#8693a5', fontSize: 10 }} tickFormatter={(value: number) => `${Math.round(value / 1000)}k`} />
                    <Tooltip formatter={(value) => `${number(Number(value))} MW`} />
                    <Bar dataKey="mae_mw" name="MAE" fill="#2866d8" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </article>

            <article className="panel chart-panel histogram-panel">
              <div className="panel-heading"><div><span className="eyebrow">ERROR DISTRIBUTION</span><h3>Forecast minus actual</h3></div></div>
              <p className="panel-subtitle">Half-hour points · positive values are over-forecasts</p>
              <div className="chart-wrap medium-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={histogramData} margin={{ top: 10, right: 8, bottom: 3, left: -8 }}>
                    <CartesianGrid stroke="#e8edf3" vertical={false} />
                    <XAxis dataKey="center" interval={3} tickLine={false} axisLine={false} tick={{ fill: '#8693a5', fontSize: 9 }} tickFormatter={(value: number) => `${Math.round(value / 1000)}k`} />
                    <YAxis tickLine={false} axisLine={false} tick={{ fill: '#8693a5', fontSize: 10 }} />
                    <Tooltip labelFormatter={(value) => `Bin centre ${number(Number(value))} MW`} />
                    <Bar dataKey="count" name="Points" radius={[3, 3, 0, 0]}>
                      {histogramData.map((bin) => <Cell key={bin.center} fill={bin.center >= 0 ? '#2866d8' : '#a9bfdc'} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </article>

            <article className="panel daily-panel">
              <div className="panel-heading"><div><span className="eyebrow">DAILY DETAIL</span><h3>Delivery-day error</h3></div></div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Delivery day</th><th>MAE</th><th>Bias</th><th>Spread</th></tr></thead>
                  <tbody>
                    {days.map((row) => <tr key={row.delivery_date}>
                      <td>{new Date(`${row.delivery_date}T12:00:00`).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}</td>
                      <td>{number(row.mae_mw)} MW</td><td>{number(row.bias_mw)} MW</td><td>{number(row.spread_mae_mw)} MW</td>
                    </tr>)}
                  </tbody>
                </table>
              </div>
            </article>
          </section>

          <section className="method-strip accuracy-method">
            <div className="method-icon">i</div>
            <div><strong>Bias and spread</strong><span>Bias is mean forecast minus actual. Spread is the mean absolute error after removing mean bias; raw spread removes the sample-mean bias in hindsight and is not directly comparable to corrected spread.</span></div>
            <div className="method-divider" />
            <div><strong>One-month limitation</strong><span>31 delivery days cannot represent seasonal or year-round performance. MAPE is omitted because it becomes unstable near zero wind.</span></div>
          </section>
        </>
      )}
    </div>
  )
}
