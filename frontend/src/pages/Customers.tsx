import { useState } from 'react'
import {
  Area,
  Bar,
  BarChart,
  ComposedChart,
  Line,
  ReferenceLine,
} from 'recharts'
import { api } from '../lib/api'
import type { Filters } from '../lib/api'
import { useApi } from '../lib/useApi'
import { axisMoney, money, num, pct } from '../lib/format'
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

export default function Customers({ filters }: { filters: Filters }) {
  const [limit, setLimit] = useState(20)
  const data = useApi(() => api.customers(filters, limit), [filters, limit])
  const segments = useApi(() => api.breakdown('segment', filters), [filters])

  if (data.error) return <ErrorBox message={data.error} />
  if (!data.data || !segments.data) return <Loading />

  const { top, deciles, order_bands, lorenz, summary, unattributed } = data.data

  // The Lorenz curve needs the origin to start at (0, 0); the API returns
  // points from the first customer onward.
  const curve = [{ customer_pct: 0, revenue_pct: 0, even: 0 }].concat(
    lorenz.map((p) => ({ ...p, even: p.customer_pct })),
  )
  const at20 = lorenz.reduce(
    (best, p) => (Math.abs(p.customer_pct - 20) < Math.abs(best.customer_pct - 20) ? p : best),
    lorenz[0] ?? { customer_pct: 0, revenue_pct: 0 },
  )

  const repeatRate =
    order_bands.length > 0
      ? 100 - (order_bands.find((b) => b.band === '1 order')?.pct_of_customers ?? 0)
      : 0

  return (
    <>
      <PageHeader title="Customer analysis">
        Concentration, value and repeat behaviour across{' '}
        {num(summary.customers)} attributed accounts.
      </PageHeader>

      <div className="kpi-row">
        <Kpi label="Customers" value={num(summary.customers)} />
        <Kpi label="Revenue per customer"
             value={money(summary.revenue / Math.max(summary.customers, 1))} />
        <Kpi label="Average order value"
             value={money(summary.revenue / Math.max(summary.transactions, 1), 0)} />
        <Kpi label="Repeat rate" value={pct(repeatRate)}
             hint="Share of customers with more than one order." />
        <Kpi label="Top decile share" value={pct(deciles[0]?.pct_of_revenue)}
             higherIsBetter={false}
             hint="Revenue share of the largest 10% of accounts — a concentration risk, so lower is safer." />
      </div>

      {unattributed.transactions > 0 && (
        <Note kind="info">
          {num(unattributed.transactions)} transactions ({money(unattributed.revenue)})
          could not be matched to a customer and are excluded from this page.
          They remain in company revenue totals — which is why customer revenue
          does not sum exactly to headline revenue. Attributing them by guesswork
          would have been the alternative, and a wrong attribution is worse than
          an acknowledged gap.
        </Note>
      )}

      <div className="grid grid-2-1">
        <Card
          title="Revenue concentration (Lorenz curve)"
          note={`The top 20% of customers generate ${pct(at20.revenue_pct)} of revenue. The further the curve bows above the diagonal, the more the business depends on a handful of accounts.`}
        >
          <ChartFrame height={320}>
            <ComposedChart data={curve} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
              <Grid />
              <XAxisStyled type="number" dataKey="customer_pct" domain={[0, 100]}
                           tickFormatter={(v: number) => `${v.toFixed(0)}%`}
                           label={{ value: '% of customers, largest first',
                                    position: 'insideBottom', offset: -2,
                                    fill: 'var(--text-faint)', fontSize: 11 }} />
              <YAxisStyled domain={[0, 100]} width={48}
                           tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
              <TooltipStyled formatter={(v: number) => pct(v, 1)}
                             labelFormatter={(l: number) => `Top ${Number(l).toFixed(1)}% of customers`} />
              <LegendStyled />
              <Area type="monotone" dataKey="revenue_pct" name="Actual"
                    stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.15} strokeWidth={2.6} />
              <Line type="linear" dataKey="even" name="Perfectly even"
                    stroke={NEUTRAL} strokeDasharray="6 4" strokeWidth={1.4} dot={false} />
              <ReferenceLine x={20} stroke={BAD} strokeDasharray="3 3" />
            </ComposedChart>
          </ChartFrame>
        </Card>

        <Card
          title="Revenue share by decile"
          note="A steep first bar is the concentration risk in one picture."
        >
          <ChartFrame height={320}>
            <BarChart data={deciles} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <Grid />
              <XAxisStyled dataKey="decile"
                           label={{ value: 'Decile (1 = largest)', position: 'insideBottom',
                                    offset: -2, fill: 'var(--text-faint)', fontSize: 11 }} />
              <YAxisStyled width={44} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
              <TooltipStyled formatter={(v: number) => pct(v, 2)}
                             labelFormatter={(l: number) => `Decile ${l}`} />
              <Bar dataKey="pct_of_revenue" name="% of revenue" fill={PALETTE[0]}
                   radius={[3, 3, 0, 0]} />
            </BarChart>
          </ChartFrame>
        </Card>
      </div>

      <Card className="mt" title="Decile detail">
        <DataTable
          rowKey={(r) => String(r.decile)}
          rows={deciles}
          columns={[
            { key: 'd', label: 'Decile', render: (r) => r.decile },
            { key: 'c', label: 'Customers', numeric: true, render: (r) => num(r.customers) },
            { key: 'rev', label: 'Revenue', numeric: true, render: (r) => money(r.revenue, 2) },
            { key: 'share', label: 'Share', numeric: true, render: (r) => pct(r.pct_of_revenue, 2) },
            { key: 'cum', label: 'Cumulative', numeric: true, render: (r) => pct(r.cumulative_pct, 2) },
            { key: 'avg', label: 'Avg per customer', numeric: true, render: (r) => money(r.avg_revenue) },
          ]}
        />
      </Card>

      <Card
        className="mt"
        title={`Top ${limit} customers by revenue`}
        note="The line is the running share of total revenue — read off how few accounts it takes to reach half the business."
      >
        <div className="row mb">
          <span className="small muted">Accounts to show</span>
          {[10, 20, 30, 50].map((n) => (
            <button key={n} className={`chip ${limit === n ? 'on' : ''}`}
                    onClick={() => setLimit(n)}>
              {n}
            </button>
          ))}
        </div>
        <ChartFrame height={330}>
          <ComposedChart data={top} margin={{ top: 8, right: 12, left: 0, bottom: 46 }}>
            <Grid />
            <XAxisStyled dataKey="customer_id" angle={-52} textAnchor="end"
                         height={70} interval={0} fontSize={9.5} />
            <YAxisStyled yAxisId="left" tickFormatter={axisMoney} />
            <YAxisStyled yAxisId="right" orientation="right" width={48} domain={[0, 100]}
                         tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
            <TooltipStyled
              formatter={(value: number, name: string) =>
                name.includes('%') ? pct(value, 2) : money(value, 2)}
            />
            <LegendStyled />
            <Bar yAxisId="left" dataKey="revenue" name="Revenue" fill={PALETTE[0]}
                 radius={[3, 3, 0, 0]} />
            <Line yAxisId="right" type="monotone" dataKey="cumulative_pct"
                  name="Cumulative % of revenue" stroke={PALETTE[1]} strokeWidth={2.4}
                  dot={{ r: 2.5 }} />
          </ComposedChart>
        </ChartFrame>

        <div className="mt">
          <DataTable
            scroll
            rowKey={(r) => r.customer_id}
            rows={top}
            columns={[
              { key: 'rank', label: '#', numeric: true, render: (r) => r.rank },
              { key: 'id', label: 'Customer', render: (r) => <span className="mono">{r.customer_id}</span> },
              { key: 'seg', label: 'Segment', render: (r) => r.customer_segment },
              { key: 'reg', label: 'Region', render: (r) => r.region },
              { key: 'orders', label: 'Orders', numeric: true, render: (r) => num(r.orders) },
              { key: 'months', label: 'Active months', numeric: true, render: (r) => num(r.active_months) },
              { key: 'rev', label: 'Revenue', numeric: true, render: (r) => money(r.revenue, 2) },
              { key: 'profit', label: 'Profit', numeric: true, render: (r) => money(r.profit, 2) },
              { key: 'margin', label: 'Margin', numeric: true, render: (r) => pct(r.profit_margin_pct, 1) },
              { key: 'aov', label: 'Avg order', numeric: true, render: (r) => money(r.avg_order_value, 0) },
              { key: 'cum', label: 'Cumulative', numeric: true, render: (r) => pct(r.cumulative_pct, 2) },
            ]}
          />
        </div>
      </Card>

      <div className="grid grid-2 mt">
        <Card title="Revenue per customer by segment">
          <ChartFrame height={280}>
            <BarChart data={segments.data} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <Grid />
              <XAxisStyled dataKey="name" />
              <YAxisStyled tickFormatter={axisMoney} />
              <TooltipStyled formatter={(v: number) => money(v, 2)} />
              <Bar dataKey="revenue" name="Revenue" fill={PALETTE[0]} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ChartFrame>
        </Card>

        <Card
          title="Customers and revenue by order count"
          note="Where the revenue bar towers over the customer bar, a small group of frequent buyers is carrying the business — the same concentration story seen from the behavioural side."
        >
          <ChartFrame height={280}>
            <BarChart data={order_bands} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <Grid />
              <XAxisStyled dataKey="band" />
              <YAxisStyled width={44} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
              <TooltipStyled formatter={(v: number) => pct(v, 2)} />
              <LegendStyled />
              <Bar dataKey="pct_of_customers" name="% of customers" fill={PALETTE[4]}
                   radius={[3, 3, 0, 0]} />
              <Bar dataKey="pct_of_revenue" name="% of revenue" fill={PALETTE[0]}
                   radius={[3, 3, 0, 0]} />
            </BarChart>
          </ChartFrame>
        </Card>
      </div>
    </>
  )
}
