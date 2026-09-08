import {
  Bar,
  BarChart,
  Cell,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  Scatter,
  ScatterChart,
  YAxis,
  ZAxis,
} from 'recharts'
import { api } from '../lib/api'
import type { Filters, ProductRow } from '../lib/api'
import { useApi } from '../lib/useApi'
import { axisMoney, money, num, pct } from '../lib/format'
import { shortMonth } from '../lib/format'
import { BAD, NEUTRAL, PALETTE } from '../lib/palette'
import { Card, DataTable, ErrorBox, Kpi, Loading, Note, PageHeader } from '../components/ui'
import {
  ChartFrame,
  Grid,
  LegendStyled,
  TooltipStyled,
  XAxisStyled,
  YAxisStyled,
} from '../components/charts'

export default function Profitability({ filters }: { filters: Filters }) {
  const kpis = useApi(() => api.kpis(filters), [filters])
  const monthly = useApi(() => api.monthly(filters), [filters])
  const categories = useApi(() => api.breakdown('category', filters), [filters])
  const regions = useApi(() => api.breakdown('region', filters), [filters])
  const bands = useApi(() => api.discountBands(filters), [filters])
  const products = useApi(() => api.products(filters), [filters])
  const stats = useApi(() => api.statistics(), [])

  if (kpis.error) return <ErrorBox message={kpis.error} />
  if (!kpis.data || !monthly.data || !categories.data || !regions.data || !bands.data || !products.data) {
    return <Loading />
  }

  const t = kpis.data.totals
  const sortedCategories = [...categories.data].sort(
    (a, b) => (a.profit_margin_pct ?? 0) - (b.profit_margin_pct ?? 0),
  )

  // The investigation screen: above-median revenue, bottom-quartile margin.
  // High volume plus thin margin is where a small pricing correction moves the
  // most money, because the volume is already proven.
  const flagged = products.data.filter(
    (p) => p.revenue_percentile >= 50 && p.margin_percentile <= 25,
  )
  const scatter = products.data.map((p) => ({
    ...p,
    flag: p.revenue_percentile >= 50 && p.margin_percentile <= 25 ? 'Investigate' : 'Normal',
  }))
  const uplift = flagged.reduce((sum, p) => sum + p.revenue * 0.01, 0)

  const discountTest = stats.data?.hypothesis_tests.find((h) => h.name === 'discount_vs_margin')

  return (
    <>
      <PageHeader title="Profitability analysis">
        Margin over time, by cut, and against discount depth.
      </PageHeader>

      <div className="kpi-row">
        <Kpi label="Gross profit" value={money(t.profit)} />
        <Kpi label="Gross margin" value={pct(t.gross_margin_pct, 2)} />
        <Kpi label="Cost-to-revenue" value={pct(t.cost_to_revenue_pct, 2)} higherIsBetter={false} />
        <Kpi label="Discount rate" value={pct(t.discount_rate_pct, 2)} higherIsBetter={false} />
        <Kpi label="Loss-making" value={pct(t.loss_making_pct, 2)} higherIsBetter={false}
             hint="Share of transactions sold below cost." />
      </div>

      <Card
        title="Gross margin and discount rate over time"
        note="Watch the two lines together: where the discount line spikes, the margin line dips shortly after. The Statistical Analysis page quantifies the relationship and reports whether it survives controlling for product mix."
      >
        <ChartFrame height={310}>
          <LineChart data={monthly.data} margin={{ top: 6, right: 10, left: 0, bottom: 0 }}>
            <Grid />
            <XAxisStyled dataKey="month_start" tickFormatter={shortMonth} minTickGap={26} />
            <YAxisStyled width={50} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
            <TooltipStyled formatter={(v: number) => pct(v, 2)}
                           labelFormatter={(l: string) => shortMonth(l)} />
            <LegendStyled />
            <Line type="monotone" dataKey="profit_margin_pct" name="Gross margin %"
                  stroke={PALETTE[0]} strokeWidth={2.4} dot={{ r: 2 }} />
            <Line type="monotone" dataKey="discount_rate_pct" name="Discount rate %"
                  stroke={PALETTE[1]} strokeWidth={2} strokeDasharray="4 3" dot={false} />
          </LineChart>
        </ChartFrame>
      </Card>

      <div className="grid grid-2 mt">
        <Card
          title="Profit margin by category"
          note="Categories below 20% margin are shown in red — they consume working capital and logistics capacity for very little return."
        >
          <ChartFrame height={300}>
            <BarChart data={sortedCategories} layout="vertical"
                      margin={{ top: 6, right: 40, left: 4, bottom: 0 }}>
              <Grid />
              <XAxisStyled type="number" tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
              <YAxis type="category" dataKey="name" width={130} stroke="var(--text-faint)"
                     fontSize={11} tickLine={false} axisLine={false} />
              <TooltipStyled formatter={(v: number) => pct(v, 2)} />
              <Bar dataKey="profit_margin_pct" name="Margin" radius={[0, 3, 3, 0]}>
                {sortedCategories.map((row) => (
                  <Cell key={row.name} fill={(row.profit_margin_pct ?? 0) < 20 ? BAD : PALETTE[0]} />
                ))}
              </Bar>
            </BarChart>
          </ChartFrame>
        </Card>

        <Card
          title="Region: scale against margin"
          note="Bubble size is absolute profit. The downward drift from left to right is the trade-off — the biggest regions discount hardest and earn least per dollar."
        >
          <ChartFrame height={300}>
            <ScatterChart margin={{ top: 10, right: 16, left: 0, bottom: 4 }}>
              <Grid />
              <XAxisStyled type="number" dataKey="revenue" name="Revenue"
                           tickFormatter={axisMoney} />
              <YAxisStyled type="number" dataKey="profit_margin_pct" name="Margin"
                           width={50} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
              <ZAxis type="number" dataKey="profit" range={[80, 620]} />
              <TooltipStyled
                cursor={{ strokeDasharray: '3 3' }}
                formatter={(value: number, name: string) =>
                  name === 'Margin' ? pct(value, 2) : money(value, 2)}
                labelFormatter={() => ''}
                content={({ active, payload }: {
                  active?: boolean
                  payload?: { payload: { name: string; revenue: number; profit: number; profit_margin_pct: number | null } }[]
                }) => {
                  if (!active || !payload?.length) return null
                  const p = payload[0].payload
                  return (
                    <div className="chart-tooltip">
                      <div className="tt-label">{p.name}</div>
                      <div className="tt-row"><span>Revenue</span><b>{money(p.revenue, 2)}</b></div>
                      <div className="tt-row"><span>Profit</span><b>{money(p.profit, 2)}</b></div>
                      <div className="tt-row"><span>Margin</span><b>{pct(p.profit_margin_pct, 2)}</b></div>
                    </div>
                  )
                }}
              />
              <Scatter data={regions.data} fill={PALETTE[0]} fillOpacity={0.75} />
            </ScatterChart>
          </ChartFrame>
        </Card>
      </div>

      <Card
        className="mt"
        title="Revenue and realised margin by discount band"
        note="The margin line falls monotonically across the bands while revenue concentrates in the middle. Note the countervailing effect: average order value rises with discount depth, so discounts are buying larger orders — the question is whether they buy enough, and past roughly 25% they demonstrably do not."
      >
        <ChartFrame height={320}>
          <ComposedChart data={bands.data} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
            <Grid />
            <XAxisStyled dataKey="band" />
            <YAxisStyled yAxisId="left" tickFormatter={axisMoney} />
            <YAxisStyled yAxisId="right" orientation="right" width={50}
                         tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
            <TooltipStyled
              formatter={(value: number, name: string) =>
                name.includes('%') ? pct(value, 2) : money(value, 2)}
            />
            <LegendStyled />
            <ReferenceLine yAxisId="right" y={0} stroke={NEUTRAL} strokeDasharray="3 3" />
            <Bar yAxisId="left" dataKey="revenue" name="Revenue" fill={PALETTE[0]}
                 fillOpacity={0.5} radius={[3, 3, 0, 0]} />
            <Line yAxisId="right" type="monotone" dataKey="profit_margin_pct"
                  name="Realised margin %" stroke={BAD} strokeWidth={2.8}
                  dot={{ r: 4 }} />
          </ComposedChart>
        </ChartFrame>

        <div className="mt">
          <DataTable
            rowKey={(r) => r.band}
            rows={bands.data}
            columns={[
              { key: 'band', label: 'Discount band', render: (r) => r.band },
              { key: 'txn', label: 'Transactions', numeric: true, render: (r) => num(r.transactions) },
              { key: 'qty', label: 'Avg qty', numeric: true, render: (r) => num(r.avg_quantity, 1) },
              { key: 'rev', label: 'Revenue', numeric: true, render: (r) => money(r.revenue, 2) },
              { key: 'given', label: 'Discount given', numeric: true, render: (r) => money(r.discount_given, 2) },
              { key: 'profit', label: 'Profit', numeric: true, render: (r) => money(r.profit, 2) },
              {
                key: 'margin', label: 'Margin', numeric: true,
                render: (r) => (
                  <span className={(r.profit_margin_pct ?? 0) < 0 ? 'neg' : ''}>
                    {pct(r.profit_margin_pct, 2)}
                  </span>
                ),
              },
              { key: 'aov', label: 'Avg order', numeric: true, render: (r) => money(r.avg_order_value, 0) },
              { key: 'loss', label: 'Loss-making', numeric: true, render: (r) => num(r.loss_making) },
            ]}
          />
        </div>
      </Card>

      {discountTest && (
        <Note kind="warn">
          <strong>Statistical confirmation.</strong> {discountTest.interpretation}
        </Note>
      )}

      <Card
        className="mt"
        title="Every product: revenue against margin"
        note="The bottom-right quadrant — above-median revenue and bottom-quartile margin — is the investigation list. High volume plus thin margin is where a small pricing correction moves the most money, because the volume is already there."
      >
        <ChartFrame height={400}>
          <ScatterChart margin={{ top: 10, right: 16, left: 0, bottom: 8 }}>
            <Grid />
            <XAxisStyled type="number" dataKey="revenue" name="Revenue"
                         tickFormatter={axisMoney} />
            <YAxisStyled type="number" dataKey="profit_margin_pct" name="Margin"
                         width={50} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
            <ZAxis type="number" dataKey="units" range={[40, 420]} />
            <TooltipStyled
              cursor={{ strokeDasharray: '3 3' }}
              content={({ active, payload }: {
                active?: boolean
                payload?: { payload: ProductRow }[]
              }) => {
                if (!active || !payload?.length) return null
                const p = payload[0].payload
                return (
                  <div className="chart-tooltip">
                    <div className="tt-label">{p.product_name}</div>
                    <div className="tt-row"><span>Category</span><b>{p.product_category}</b></div>
                    <div className="tt-row"><span>Revenue</span><b>{money(p.revenue, 2)}</b></div>
                    <div className="tt-row"><span>Margin</span><b>{pct(p.profit_margin_pct, 2)}</b></div>
                    <div className="tt-row"><span>Units</span><b>{num(p.units)}</b></div>
                  </div>
                )
              }}
            />
            <LegendStyled />
            <Scatter name="Normal" data={scatter.filter((p) => p.flag === 'Normal')}
                     fill={PALETTE[0]} fillOpacity={0.55} />
            <Scatter name="Investigate" data={scatter.filter((p) => p.flag === 'Investigate')}
                     fill={BAD} fillOpacity={0.85} />
          </ScatterChart>
        </ChartFrame>
      </Card>

      {flagged.length > 0 && (
        <Card className="mt" title={`Investigation list — ${flagged.length} products`}>
          <DataTable
            rowKey={(r) => r.product_id}
            rows={[...flagged].sort((a, b) => b.revenue - a.revenue)}
            columns={[
              { key: 'id', label: 'Product', render: (r) => <span className="mono">{r.product_id}</span> },
              { key: 'name', label: 'Name', render: (r) => r.product_name },
              { key: 'cat', label: 'Category', render: (r) => r.product_category },
              { key: 'units', label: 'Units', numeric: true, render: (r) => num(r.units) },
              { key: 'rev', label: 'Revenue', numeric: true, render: (r) => money(r.revenue, 2) },
              {
                key: 'margin', label: 'Margin', numeric: true,
                render: (r) => <span className="neg">{pct(r.profit_margin_pct, 2)}</span>,
              },
              { key: 'disc', label: 'Discount rate', numeric: true, render: (r) => pct(r.discount_rate_pct, 2) },
              {
                key: 'uplift', label: 'Value of +1pp margin', numeric: true,
                render: (r) => money(r.revenue * 0.01, 0),
              },
            ]}
          />
          <Note kind="ok">
            Recovering one percentage point of margin across these{' '}
            {flagged.length} products would be worth <strong>{money(uplift)}</strong>{' '}
            a year at current volume, with no additional sales effort. A
            five-point recovery would be worth {money(uplift * 5)}.
          </Note>
        </Card>
      )}
    </>
  )
}
