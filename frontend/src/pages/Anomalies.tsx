import { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ReferenceLine,
  Scatter,
  ScatterChart,
  ZAxis,
} from 'recharts'
import { api } from '../lib/api'
import type { AnomalyRow } from '../lib/api'
import { useApi } from '../lib/useApi'
import { num, pct, shortMonth, signedPct } from '../lib/format'
import { NEUTRAL, PALETTE, SEVERITY_COLOR, SEVERITY_ORDER } from '../lib/palette'
import { Card, DataTable, ErrorBox, Kpi, Loading, Note, PageHeader } from '../components/ui'
import {
  ChartFrame,
  Grid,
  LegendStyled,
  TooltipStyled,
  XAxisStyled,
  YAxisStyled,
} from '../components/charts'

export default function Anomalies() {
  const data = useApi(() => api.anomalies(), [])
  const [severities, setSeverities] = useState<string[]>(['Critical', 'High'])
  const [materialOnly, setMaterialOnly] = useState(true)
  const [selected, setSelected] = useState<AnomalyRow | null>(null)

  const rows = data.data?.rows ?? []

  const filtered = useMemo(
    () =>
      rows.filter(
        (r) =>
          (severities.length === 0 || severities.includes(r.severity)) &&
          (!materialOnly || r.material),
      ),
    [rows, severities, materialOnly],
  )

  if (data.error) return <ErrorBox message={data.error} />
  if (!data.data) return <Loading />

  const report = data.data
  const scoring = report.ground_truth_scoring

  const severityCounts = SEVERITY_ORDER.map((s) => ({
    severity: s,
    count: report.by_severity[s] ?? 0,
  })).filter((s) => s.count > 0)

  // Method strings carry their parameters ("Tukey IQR fences (k=1.5) on log
  // scale"), and two variants can shorten to the same detector name. Sum them
  // after shortening, or the pie shows one detector twice.
  const methodCounts = Object.entries(
    Object.entries(report.by_method).reduce<Record<string, number>>((acc, [method, count]) => {
      const name = method.split('(')[0].trim()
      acc[name] = (acc[name] ?? 0) + count
      return acc
    }, {}),
  )
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)

  // Undated flags are transaction-level (IQR on individual rows) and have no
  // place on a timeline.
  const dated = filtered.filter((r) => /^\d{4}-\d{2}-\d{2}$/.test(r.period))
  const timeline = dated.map((r) => ({
    ...r,
    ts: new Date(r.period).getTime(),
    size: Math.min(Math.abs(r.score), 20),
  }))

  const toggleSeverity = (s: string) =>
    setSeverities((prev) => (prev.includes(s) ? prev.filter((v) => v !== s) : [...prev, s]))

  return (
    <>
      <PageHeader title="Anomaly monitor">
        Four classical detectors — global z-score, rolling z-score,
        seasonal-residual z-score and Tukey IQR fences. No machine learning:
        every threshold has an explicit meaning, which matters because a finance
        team has to act on the output and defend it.
      </PageHeader>

      <Note kind="info">
        Computed on the full unfiltered dataset by <code>src/anomaly.py</code>.
        The detectors need complete series to establish what "normal" looks
        like, so the sidebar filters do not apply to this page.
      </Note>

      <div className="kpi-row">
        <Kpi label="Total flags" value={num(report.total_anomalies)} />
        <Kpi label="Material" value={num(report.material_flags)}
             hint={`Flags that also cleared the ${report.materiality_threshold_pct}% relative-change floor.`} />
        <Kpi label="Critical" value={num(report.by_severity.Critical ?? 0)} />
        {scoring.available && (
          <Kpi label="Detector recall" value={pct(scoring.recall_pct, 0)}
               hint={`${scoring.events_recovered} of ${scoring.events_injected} known events recovered.`} />
        )}
      </div>

      <details className="mb">
        <summary>Why some flags are capped at Low severity</summary>
        <div className="details-body">
          <p>
            A z-score measures how <em>statistically</em> unusual a value is,
            not how much it matters. Series with very little natural variance —
            fixed rent, depreciation — produce enormous z-scores for changes
            nobody would act on: a 2.7% increase in facilities cost scored above
            z = 9 in this dataset.
          </p>
          <p style={{ marginBottom: 0 }}>
            Ranking purely by z-score would put those at the top of this monitor
            and bury a 48% revenue collapse beneath them. So a flag must clear{' '}
            <strong>both</strong> the z threshold{' '}
            <strong>and</strong> a relative-change floor of{' '}
            {report.materiality_threshold_pct}% before it can be graded above
            Low. Immaterial flags are still reported — they are real — they just
            cannot crowd out the actionable ones.
          </p>
        </div>
      </details>

      <div className="grid grid-2">
        <Card title="Flags by severity">
          <ChartFrame height={280}>
            <BarChart data={severityCounts} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <Grid />
              <XAxisStyled dataKey="severity" />
              <YAxisStyled width={44} />
              <TooltipStyled />
              <Bar dataKey="count" name="Flags" radius={[3, 3, 0, 0]}>
                {severityCounts.map((s) => (
                  <Cell key={s.severity} fill={SEVERITY_COLOR[s.severity]} />
                ))}
              </Bar>
            </BarChart>
          </ChartFrame>
        </Card>

        <Card
          title="Flags by detector"
          note="Four detectors run side by side because each is blind to something the others catch: a global z-score on a growing series mostly rediscovers 'December is big', while the seasonal-residual detector is the only one that can tell an unusually bad February from an ordinary one."
        >
          <ChartFrame height={280}>
            <PieChart>
              <Pie data={methodCounts} dataKey="value" nameKey="name"
                   innerRadius={58} outerRadius={98} paddingAngle={2}
                   label={(e: { percent?: number }) => `${((e.percent ?? 0) * 100).toFixed(0)}%`}
                   labelLine={false}>
                {methodCounts.map((entry, i) => (
                  <Cell key={entry.name} fill={PALETTE[i % PALETTE.length]} />
                ))}
              </Pie>
              <TooltipStyled />
              <LegendStyled />
            </PieChart>
          </ChartFrame>
        </Card>
      </div>

      <Card
        className="mt"
        title="Anomalies over time"
        note="Vertical clusters are the periods worth investigating — several independent metrics breaking at the same time is a business event, whereas an isolated point is usually noise."
      >
        <ChartFrame height={380}>
          <ScatterChart margin={{ top: 10, right: 16, left: 0, bottom: 8 }}>
            <Grid />
            <XAxisStyled type="number" dataKey="ts" domain={['dataMin', 'dataMax']}
                         tickFormatter={(v: number) => shortMonth(new Date(v).toISOString())}
                         scale="time" />
            <YAxisStyled type="number" dataKey="score" name="z-score" width={50} />
            <ZAxis type="number" dataKey="size" range={[40, 420]} />
            <ReferenceLine y={0} stroke={NEUTRAL} />
            <TooltipStyled
              cursor={{ strokeDasharray: '3 3' }}
              content={({ active, payload }: {
                active?: boolean
                payload?: { payload: AnomalyRow }[]
              }) => {
                if (!active || !payload?.length) return null
                const a = payload[0].payload
                return (
                  <div className="chart-tooltip">
                    <div className="tt-label">{a.period} · {a.severity}</div>
                    <div className="tt-row"><span>Scope</span><b>{a.scope}</b></div>
                    <div className="tt-row"><span>Metric</span><b>{a.metric}</b></div>
                    <div className="tt-row"><span>Deviation</span><b>{signedPct(a.deviation_pct)}</b></div>
                    <div className="tt-row"><span>z-score</span><b>{a.score.toFixed(2)}</b></div>
                  </div>
                )
              }}
            />
            <LegendStyled />
            {SEVERITY_ORDER.filter((s) => timeline.some((t) => t.severity === s)).map((s) => (
              <Scatter key={s} name={s} data={timeline.filter((t) => t.severity === s)}
                       fill={SEVERITY_COLOR[s]} fillOpacity={0.78} />
            ))}
          </ScatterChart>
        </ChartFrame>
      </Card>

      <Card className="mt" title="Anomaly register">
        <div className="row mb">
          <span className="small muted">Severity</span>
          {SEVERITY_ORDER.map((s) => (
            <button key={s} className={`chip ${severities.includes(s) ? 'on' : ''}`}
                    onClick={() => toggleSeverity(s)}>
              {s}
            </button>
          ))}
          <span className="spacer" />
          <button className={`chip ${materialOnly ? 'on' : ''}`}
                  onClick={() => setMaterialOnly(!materialOnly)}>
            Material only
          </button>
        </div>

        <p className="small muted">
          {num(filtered.length)} flags match. Click a row to read its
          interpretation.
        </p>

        <DataTable
          scroll
          rowKey={(r, i) => `${r.period}-${r.scope}-${r.metric}-${i}`}
          rows={filtered}
          onRowClick={setSelected}
          selectedKey={
            selected
              ? `${selected.period}-${selected.scope}-${selected.metric}-${filtered.indexOf(selected)}`
              : undefined
          }
          columns={[
            { key: 'period', label: 'Period', render: (r) => r.period },
            {
              key: 'sev', label: 'Severity',
              render: (r) => (
                <span className={`badge ${r.severity.toLowerCase()}`}>{r.severity}</span>
              ),
            },
            { key: 'scope', label: 'Scope', render: (r) => r.scope },
            { key: 'metric', label: 'Metric', render: (r) => r.metric },
            { key: 'actual', label: 'Actual', numeric: true, render: (r) => num(r.actual, 2) },
            { key: 'expected', label: 'Expected', numeric: true, render: (r) => num(r.expected, 2) },
            {
              key: 'range', label: 'Expected range', numeric: true,
              render: (r) => `${num(r.expected_low, 2)} – ${num(r.expected_high, 2)}`,
            },
            {
              key: 'dev', label: 'Deviation', numeric: true,
              render: (r) => (
                <span className={r.deviation_pct < 0 ? 'neg' : 'pos'}>
                  {signedPct(r.deviation_pct)}
                </span>
              ),
            },
            { key: 'z', label: 'z', numeric: true, render: (r) => r.score.toFixed(2) },
          ]}
        />

        {selected && (
          <div className="mt">
            <h3 className="mb">
              {selected.period} · {selected.scope} · {selected.metric}
            </h3>
            <div className="kpi-row">
              <Kpi label="Actual" value={num(selected.actual, 2)} />
              <Kpi label="Expected" value={num(selected.expected, 2)} />
              <Kpi label="Deviation" value={signedPct(selected.deviation_pct)}
                   higherIsBetter={selected.deviation_pct >= 0} />
              <Kpi label="z-score" value={selected.score.toFixed(2)} />
            </div>
            <p className="small muted">
              <strong>Method:</strong> {selected.method}
              <br />
              <strong>Expected range:</strong> {num(selected.expected_low, 2)} to{' '}
              {num(selected.expected_high, 2)}
            </p>
            <Note kind={selected.severity === 'Critical' ? 'danger' : 'info'}>
              {selected.interpretation}
            </Note>
          </div>
        )}
      </Card>

      {scoring.available && scoring.events && (
        <Card
          className="mt"
          title="Detector validation"
          subtitle="Recall measured against events recorded before any analysis ran"
        >
          <p className="small muted">
            The dataset was generated with a set of business events deliberately
            injected and written to <code>data/raw/_injected_events.json</code>{' '}
            <strong>before</strong> any analysis ran. Scoring the detectors
            against that record turns "the monitor found some anomalies" into a
            measurable recall — and makes a missed event visible instead of
            invisible.
          </p>

          <DataTable
            rowKey={(r) => r.event_id}
            rows={scoring.events}
            columns={[
              { key: 'id', label: 'Event', render: (r) => <span className="mono">{r.event_id}</span> },
              { key: 'kind', label: 'Type', render: (r) => r.kind.replace(/_/g, ' ') },
              { key: 'window', label: 'Window', render: (r) => r.window },
              {
                key: 'outcome', label: 'Outcome',
                render: (r) => (
                  <span className={`badge ${r.detected ? 'good' : 'critical'}`}>
                    {r.detected ? 'Detected' : 'MISSED'}
                  </span>
                ),
              },
              { key: 'flags', label: 'Flags', numeric: true, render: (r) => num(r.n_matching_flags) },
              { key: 'desc', label: 'Description',
                render: (r) => <span style={{ whiteSpace: 'normal' }}>{r.description}</span> },
            ]}
          />

          <Note kind="ok">
            Recall: {scoring.events_recovered}/{scoring.events_injected} injected
            events recovered ({pct(scoring.recall_pct, 0)}).
          </Note>
          <p className="small faint">{scoring.note}</p>
        </Card>
      )}
    </>
  )
}
