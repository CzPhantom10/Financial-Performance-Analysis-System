import { useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  ComposedChart,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
} from 'recharts'
import { api } from '../lib/api'
import type { Filters } from '../lib/api'
import { useApi } from '../lib/useApi'
import { axisMoney, money, num, pct, shortMonth, signedPct } from '../lib/format'
import { BAD, GOOD, NEUTRAL, PALETTE } from '../lib/palette'
import { Card, DataTable, ErrorBox, Loading, Note, PageHeader, Tabs } from '../components/ui'
import type { Column } from '../components/ui'
import type { YearPoint } from '../lib/api'
import {
  ChartFrame,
  Grid,
  LegendStyled,
  TooltipStyled,
  XAxisStyled,
  YAxisStyled,
} from '../components/charts'

const TABS = ['Trend', 'Mix', 'Growth', 'Seasonality']

export default function Revenue({ filters }: { filters: Filters }) {
  const [tab, setTab] = useState(TABS[0])
  const monthly = useApi(() => api.monthly(filters), [filters])
  const yearly = useApi(() => api.yearly(filters), [filters])
  const categories = useApi(() => api.breakdown('category', filters), [filters])
  const segments = useApi(() => api.breakdown('segment', filters), [filters])
  const regionMonthly = useApi(() => api.regionMonthly(filters), [filters])
  const timeseries = useApi(() => api.timeseries(), [])
  const components = useApi(() => api.seasonalComponents(), [])

  if (monthly.error) return <ErrorBox message={monthly.error} />
  if (!monthly.data || !categories.data || !segments.data) return <Loading />

  const months = monthly.data
  const cumulative = months.map((m) => ({
    month_start: m.month_start,
    cumulative_revenue: m.cumulative_revenue,
  }))
  const mom = months.filter((m) => m.revenue_mom_pct !== null)
  const yoy = months.filter((m) => m.revenue_yoy_pct !== null)

  // Region x month pivot, rendered as one line per region.
  const regionNames = [...new Set((regionMonthly.data ?? []).map((r) => r.region))]
  const pivot = Object.values(
    (regionMonthly.data ?? []).reduce<Record<string, Record<string, number | string>>>(
      (acc, row) => {
        acc[row.month_start] ??= { month_start: row.month_start }
        acc[row.month_start][row.region] = row.revenue
        return acc
      },
      {},
    ),
  ).sort((a, b) => String(a.month_start).localeCompare(String(b.month_start)))

  const growthColumns: Column<YearPoint>[] = [
    { key: 'year', label: 'Year', render: (r) => r.year },
    {
      key: 'rev', label: 'Revenue growth', numeric: true,
      render: (r) => <span className={(r.revenue_growth_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
        {signedPct(r.revenue_growth_pct)}</span>,
    },
    { key: 'vol', label: 'Volume growth', numeric: true, render: (r) => signedPct(r.volume_growth_pct) },
    {
      key: 'aov', label: 'Order value growth', numeric: true,
      render: (r) => {
        // revenue = transactions x AOV, so AOV growth is what revenue growth
        // leaves over once volume growth is taken out.
        if (r.revenue_growth_pct === null || r.volume_growth_pct === null) return '—'
        const aov = ((1 + r.revenue_growth_pct / 100) / (1 + r.volume_growth_pct / 100) - 1) * 100
        return signedPct(aov)
      },
    },
    { key: 'cost', label: 'Cost growth', numeric: true,
      render: (r) => <span className="neg">{signedPct(r.cost_growth_pct)}</span> },
  ]

  return (
    <>
      <PageHeader title="Revenue analysis">
        Where revenue comes from and how it is moving. {num(months.length)} months
        in the current selection.
      </PageHeader>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Trend' && (
        <div className="stack">
          <Card
            title="Monthly revenue against its 3-month moving average"
            note="Where the solid line crosses below the dotted one, the month underperformed its own recent trend. Sustained gaps — not single crossings — are what warrant attention."
          >
            <ChartFrame height={330}>
              <LineChart data={months} margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
                <Grid />
                <XAxisStyled dataKey="month_start" tickFormatter={shortMonth} minTickGap={26} />
                <YAxisStyled tickFormatter={axisMoney} />
                <TooltipStyled formatter={(v: number) => money(v, 2)}
                               labelFormatter={(l: string) => shortMonth(l)} />
                <LegendStyled />
                <Line type="monotone" dataKey="revenue" name="Revenue"
                      stroke={PALETTE[0]} strokeWidth={2} dot={{ r: 2 }} />
                <Line type="monotone" dataKey="revenue_ma3" name="3-month MA"
                      stroke={PALETTE[1]} strokeWidth={2.6} strokeDasharray="5 4" dot={false} />
              </LineChart>
            </ChartFrame>
          </Card>

          <Card
            title="Cumulative revenue"
            note="A straightening curve would mean growth is slowing; a steepening one means it is compounding."
          >
            <ChartFrame height={260}>
              <AreaChart data={cumulative} margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
                <Grid />
                <XAxisStyled dataKey="month_start" tickFormatter={shortMonth} minTickGap={26} />
                <YAxisStyled tickFormatter={axisMoney} />
                <TooltipStyled formatter={(v: number) => money(v, 2)}
                               labelFormatter={(l: string) => shortMonth(l)} />
                <Area type="monotone" dataKey="cumulative_revenue" name="Cumulative revenue"
                      stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.16} strokeWidth={2} />
              </AreaChart>
            </ChartFrame>
          </Card>
        </div>
      )}

      {tab === 'Mix' && (
        <div className="stack">
          <div className="grid grid-2">
            <Card title="Revenue by product category">
              <ChartFrame height={300}>
                <BarChart data={categories.data} margin={{ top: 6, right: 8, left: 0, bottom: 46 }}>
                  <Grid />
                  <XAxisStyled dataKey="name" angle={-28} textAnchor="end" height={60} interval={0} />
                  <YAxisStyled tickFormatter={axisMoney} />
                  <TooltipStyled formatter={(v: number) => money(v, 2)} />
                  <Bar dataKey="revenue" name="Revenue" fill={PALETTE[0]} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ChartFrame>
            </Card>

            <Card title="Revenue by customer segment">
              <ChartFrame height={300}>
                <PieChart>
                  <Pie data={segments.data} dataKey="revenue" nameKey="name"
                       innerRadius={62} outerRadius={104} paddingAngle={2}
                       label={(e: { name?: string; percent?: number }) =>
                         `${e.name} ${((e.percent ?? 0) * 100).toFixed(0)}%`}
                       labelLine={false}>
                    {segments.data.map((entry, i) => (
                      <Cell key={entry.name} fill={PALETTE[i % PALETTE.length]} />
                    ))}
                  </Pie>
                  <TooltipStyled formatter={(v: number) => money(v, 2)} />
                </PieChart>
              </ChartFrame>
            </Card>
          </div>

          <Card
            title="Revenue by region over time"
            note="A dip shared by every line is a company-wide event; a dip in one line alone is a regional problem."
          >
            <ChartFrame height={320}>
              <LineChart data={pivot} margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
                <Grid />
                <XAxisStyled dataKey="month_start" tickFormatter={shortMonth} minTickGap={26} />
                <YAxisStyled tickFormatter={axisMoney} />
                <TooltipStyled formatter={(v: number) => money(v, 2)}
                               labelFormatter={(l: string) => shortMonth(l)} />
                <LegendStyled />
                {regionNames.map((region, i) => (
                  <Line key={region} type="monotone" dataKey={region} name={region}
                        stroke={PALETTE[i % PALETTE.length]} strokeWidth={1.9} dot={false} />
                ))}
              </LineChart>
            </ChartFrame>
          </Card>

          <Card title="Category detail">
            <DataTable
              rowKey={(r) => r.name}
              rows={categories.data}
              columns={[
                { key: 'name', label: 'Category', render: (r) => r.name },
                { key: 'rev', label: 'Revenue', numeric: true, render: (r) => money(r.revenue, 2) },
                { key: 'share', label: 'Share', numeric: true, render: (r) => pct(r.pct_of_revenue) },
                { key: 'profit', label: 'Profit', numeric: true, render: (r) => money(r.profit, 2) },
                { key: 'ps', label: 'Profit share', numeric: true, render: (r) => pct(r.pct_of_profit) },
                { key: 'margin', label: 'Margin', numeric: true, render: (r) => pct(r.profit_margin_pct, 2) },
                { key: 'aov', label: 'Avg order', numeric: true, render: (r) => money(r.avg_order_value, 0) },
                { key: 'disc', label: 'Discount rate', numeric: true, render: (r) => pct(r.discount_rate_pct, 2) },
              ]}
            />
          </Card>
        </div>
      )}

      {tab === 'Growth' && (
        <div className="stack">
          <Card
            title="Month-on-month revenue growth"
            note="Month-on-month growth in a seasonal business is mostly a picture of the calendar. Read the year-on-year chart below for the real signal, and the Anomaly Monitor for deviations from the seasonally adjusted expectation."
          >
            <ChartFrame height={280}>
              <BarChart data={mom} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                <Grid />
                <XAxisStyled dataKey="month_start" tickFormatter={shortMonth} minTickGap={26} />
                <YAxisStyled width={48} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
                <TooltipStyled formatter={(v: number) => signedPct(v, 2)}
                               labelFormatter={(l: string) => shortMonth(l)} />
                <ReferenceLine y={0} stroke={NEUTRAL} />
                <Bar dataKey="revenue_mom_pct" name="MoM growth" radius={[2, 2, 0, 0]}>
                  {mom.map((r) => (
                    <Cell key={r.month_start} fill={(r.revenue_mom_pct ?? 0) >= 0 ? GOOD : BAD} />
                  ))}
                </Bar>
              </BarChart>
            </ChartFrame>
          </Card>

          <Card title="Year-on-year revenue growth">
            {yoy.length === 0 ? (
              <Note kind="info">Needs at least 13 months inside the current filter.</Note>
            ) : (
              <ChartFrame height={280}>
                <BarChart data={yoy} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                  <Grid />
                  <XAxisStyled dataKey="month_start" tickFormatter={shortMonth} minTickGap={26} />
                  <YAxisStyled width={48} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
                  <TooltipStyled formatter={(v: number) => signedPct(v, 2)}
                                 labelFormatter={(l: string) => shortMonth(l)} />
                  <ReferenceLine y={0} stroke={NEUTRAL} />
                  <Bar dataKey="revenue_yoy_pct" name="YoY growth" radius={[2, 2, 0, 0]}>
                    {yoy.map((r) => (
                      <Cell key={r.month_start} fill={(r.revenue_yoy_pct ?? 0) >= 0 ? GOOD : BAD} />
                    ))}
                  </Bar>
                </BarChart>
              </ChartFrame>
            )}
          </Card>

          <Card
            title="Growth decomposition"
            note="Revenue = transactions x average order value. Volume-led growth scales the cost base with it; order-value-led growth does not — which changes what a margin decline means."
          >
            {yearly.data && yearly.data.length > 1 ? (
              <DataTable
                rowKey={(r) => String(r.year)}
                rows={yearly.data.filter((r) => r.revenue_growth_pct !== null)}
                columns={growthColumns}
              />
            ) : (
              <Note kind="info">Needs more than one year inside the current filter.</Note>
            )}
          </Card>
        </div>
      )}

      {tab === 'Seasonality' && (
        <div className="stack">
          <Note kind="info">
            Computed on the full unfiltered dataset by <code>src/timeseries.py</code>.
            A seasonal decomposition needs the complete series to be meaningful,
            so the sidebar filters do not apply to this tab.
          </Note>

          {timeseries.data && (
            <>
              <Card
                title="Seasonal index — typical deviation from trend"
                note={timeseries.data.seasonality.interpretation}
              >
                <ChartFrame height={300}>
                  <BarChart data={timeseries.data.seasonality.seasonal_index}
                            margin={{ top: 6, right: 8, left: 0, bottom: 40 }}>
                    <Grid />
                    <XAxisStyled dataKey="month_name" angle={-30} textAnchor="end"
                                 height={54} interval={0} />
                    <YAxisStyled width={48} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
                    <TooltipStyled formatter={(v: number) => signedPct(v, 1)} />
                    <ReferenceLine y={0} stroke={NEUTRAL} />
                    <Bar dataKey="pct_vs_average" name="vs trend" radius={[2, 2, 0, 0]}>
                      {timeseries.data.seasonality.seasonal_index.map((row) => (
                        <Cell key={row.month} fill={row.pct_vs_average >= 0 ? GOOD : BAD} />
                      ))}
                    </Bar>
                  </BarChart>
                </ChartFrame>
              </Card>

              <Card title="Trend and growth">
                <div className="kpi-row" style={{ marginBottom: 0 }}>
                  <div className="kpi">
                    <div className="kpi-label">CAGR</div>
                    <div className="kpi-value">{pct(timeseries.data.trend.cagr_pct)}</div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Seasonal strength</div>
                    <div className="kpi-value">
                      {timeseries.data.seasonality.seasonal_strength.toFixed(3)}
                    </div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Peak month</div>
                    <div className="kpi-value" style={{ fontSize: '1.1rem' }}>
                      {timeseries.data.seasonality.peak_month}
                    </div>
                  </div>
                  <div className="kpi">
                    <div className="kpi-label">Trough month</div>
                    <div className="kpi-value" style={{ fontSize: '1.1rem' }}>
                      {timeseries.data.seasonality.trough_month}
                    </div>
                  </div>
                </div>
                <div className="card-note">{timeseries.data.trend.interpretation}</div>
              </Card>
            </>
          )}

          {components.data && components.data.length > 0 && (
            <Card
              title="Observed revenue and the extracted trend"
              note="The trend line is what remains once the seasonal cycle and the noise are removed — the growth path the business is actually on."
            >
              <ChartFrame height={300}>
                <ComposedChart data={components.data} margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
                  <Grid />
                  <XAxisStyled dataKey="month_start" tickFormatter={shortMonth} minTickGap={26} />
                  <YAxisStyled tickFormatter={axisMoney} />
                  <TooltipStyled formatter={(v: number) => money(v, 2)}
                                 labelFormatter={(l: string) => shortMonth(l)} />
                  <LegendStyled />
                  <Line type="monotone" dataKey="observed" name="Observed"
                        stroke={NEUTRAL} strokeWidth={1.6} dot={false} />
                  <Line type="monotone" dataKey="stl_trend" name="STL trend"
                        stroke={PALETTE[2]} strokeWidth={2.8} dot={false} />
                </ComposedChart>
              </ChartFrame>
            </Card>
          )}
        </div>
      )}
    </>
  )
}
