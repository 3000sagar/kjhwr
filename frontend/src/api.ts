export type Mode = 'raw' | 'bias_corrected'

export interface DeliveryDay {
  delivery_date: string
  expected: number
  with_forecast: number
}

export interface DayPoint {
  start_time: string
  forecast_mw: number | null
  publish_time: string | null
  horizon_h: number | null
  actual_mw: number | null
  error_mw: number | null
  band_low_mw: number | null
  band_high_mw: number | null
}

export interface DayData {
  delivery_date: string
  cutoff: string
  mode: Mode
  points: DayPoint[]
  summary: {
    forecast_mwh: number
    actual_mwh: number
    peak_forecast_mw: number | null
    min_forecast_mw: number | null
    mae_mw: number | null
    bias_mw: number | null
    spread_mae_mw: number | null
    coverage: number
  }
}

export interface AccuracySummary {
  from_date: string
  to_date: string
  cutoff: string
  mode: Mode
  mae_mw: number
  rmse_mw: number
  bias_mw: number
  spread_mae_mw: number
  nmae: number
  buffer_p90_mw: number
  buffer_p90_ci_low_mw: number | null
  buffer_p90_ci_high_mw: number | null
  raw_minus_corrected_mae_mw: number
  raw_minus_corrected_mae_ci_low_mw: number
  raw_minus_corrected_mae_ci_high_mw: number
  raw_minus_corrected_buffer_p90_mw: number
  raw_minus_corrected_buffer_p90_ci_low_mw: number
  raw_minus_corrected_buffer_p90_ci_high_mw: number
  ci_level: number
  ci_method: string
  n_hourly_forecasts: number
  n_half_hour_points: number
  coverage: number
}

export interface HourMetric {
  hour: number
  mae_mw: number
  bias_mw: number
  spread_mae_mw: number
  q10: number
  q90: number
  n_hourly_forecasts: number
}

export interface DayMetric {
  delivery_date: string
  mae_mw: number
  bias_mw: number
  spread_mae_mw: number
  n_hourly_forecasts: number
}

export interface HorizonMetric {
  horizon_bucket: string
  mae_mw: number
  bias_mw: number
  spread_mae_mw: number
  n_hourly_forecasts: number
}

export interface HistogramBin {
  bin_low_mw: number
  bin_high_mw: number
  count: number
}

async function getJson<T>(path: string): Promise<T> {
  const requestUrl = new URL(path, window.location.href).href
  let response: Response
  try {
    // Keep the request relative so the same frontend works on local and hosted origins.
    response = await fetch(path)
  } catch (reason) {
    throw new Error(`HTTP status unavailable for ${requestUrl}: ${errorMessage(reason)}`)
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json() as { detail?: string }
      detail = body.detail ?? detail
    } catch {
      // Keep the HTTP status text when an error body is not JSON.
    }
    throw new Error(`HTTP ${response.status} for ${requestUrl}: ${detail}`)
  }

  try {
    return await response.json() as T
  } catch (reason) {
    throw new Error(`HTTP ${response.status} for ${requestUrl}: invalid JSON response (${errorMessage(reason)})`)
  }
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason)
}

function commonQuery(cutoff: string, mode: Mode): URLSearchParams {
  return new URLSearchParams({ cutoff, mode })
}

export function getDeliveryDays(cutoff: string, mode: Mode): Promise<DeliveryDay[]> {
  return getJson(`/api/delivery-days?${commonQuery(cutoff, mode)}`)
}

export function getDay(day: string, cutoff: string, mode: Mode): Promise<DayData> {
  return getJson(`/api/day/${day}?${commonQuery(cutoff, mode)}`)
}

export function getSummary(cutoff: string, mode: Mode): Promise<AccuracySummary> {
  const query = commonQuery(cutoff, mode)
  query.set('from', '2026-01-02')
  query.set('to', '2026-02-01')
  return getJson(`/api/accuracy/summary?${query}`)
}

export async function getAccuracyCharts(cutoff: string, mode: Mode) {
  const query = commonQuery(cutoff, mode)
  const [byHour, byDay, byHorizon, histogram] = await Promise.all([
    getJson<HourMetric[]>(`/api/accuracy/by-hour?${query}`),
    getJson<DayMetric[]>(`/api/accuracy/by-day?${query}`),
    getJson<HorizonMetric[]>(`/api/accuracy/by-horizon?${query}`),
    getJson<HistogramBin[]>(`/api/accuracy/histogram?${query}`),
  ])
  return { byHour, byDay, byHorizon, histogram }
}
