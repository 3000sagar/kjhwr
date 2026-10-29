interface MetricCardProps {
  label: string
  value: string
  detail?: string
  help?: string
  tone?: 'blue' | 'amber' | 'green' | 'neutral'
}

export default function MetricCard({ label, value, detail, help, tone = 'neutral' }: MetricCardProps) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <div className="metric-label">
        {label}
        {help && <span className="help-tip" title={help} aria-label={help}>?</span>}
      </div>
      <strong className="metric-value">{value}</strong>
      {detail && <span className="metric-detail">{detail}</span>}
    </article>
  )
}
