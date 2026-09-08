import { useState } from 'react'
import {
  Bar,
  BarChart,
  Cell,
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
import { BAD, GOOD, NEUTRAL, PALETTE } from '../lib/palette'
import { Card, DataTable, ErrorBox, Kpi, Loading, PageHeader, Tabs } from '../components/ui'
import {
  ChartFrame,
  Grid,
  LegendStyled,
  TooltipStyled,
  XAxisStyled,
  YAxisStyled,
} from '../components/charts'

const TABS = ['Best sellers', 'Most profitable', 'Discount-heavy', 'Portfolio matrix']

function median(values: number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

function ProductTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: { payload: ProductRow }[]
}) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="chart-tooltip">
      <div className="tt-label">{p.product_name}</div>
      <div className="tt-row"><span>Category</span><b>{p.product_category}</b></div>
      <div className="tt-row"><span>Units</span><b>{num(p.units)}</b></div>
      <div className="tt-row"><span>Revenue</span><b>{money(p.revenue, 2)}</b></div>
      <div className="tt-row"><span>Margin</span><b>{pct(p.profit_margin_pct, 2)}</b></div>
    </div>
  )
}

export default function Products({ filters }: { filters: Filters }) {
  const [tab, setTab] = useState(TABS[0])
  const products = useApi(() => api.products(filters), [filters])

  if (products.error) return <ErrorBox message={products.error} />
  if (!products.data) return <Loading />

  const rows = products.data
  const margins = rows.map((p) => p.profit_margin_pct ?? 0)
  const medianUnits = median(rows.map((p) => p.units))
  const medianMargin = median(margins)

  const topUnits = [...rows].sort((a, b) => b.units - a.units).slice(0, 15).reverse()
  const topRevenue = [...rows].sort((a, b) => b.revenue - a.revenue).slice(0, 15).reverse()
  const topProfit = [...rows].sort((a, b) => b.profit - a.profit).slice(0, 15).reverse()
  const worstMargin = [...rows]
    .sort((a, b) => (a.profit_margin_pct ?? 0) - (b.profit_margin_pct ?? 0))
    .slice(0, 15)
    .reverse()

  // Low-volume products are excluded from the discount ranking so one heavily
  // discounted order cannot top the list.
  const volumeFloor = median(rows.map((p) => p.units)) * 0.25
  const discountHeavy = rows
    .filter((p) => p.units >= volumeFloor)
    .sort((a, b) => (b.discount_rate_pct ?? 0) - (a.discount_rate_pct ?? 0))
    .slice(0, 20)

  const quadrantOf = (p: ProductRow) => {
    const highVolume = p.units >= medianUnits
    const highMargin = (p.profit_margin_pct ?? 0) >= medianMargin
    if (highVolume && highMargin) return 'Star — high volume, high margin'
    if (highVolume) return 'Fix — high volume, low margin'
    if (highMargin) return 'Grow — low volume, high margin'
    return 'Review — low volume, low margin'
  }
  const QUADRANTS = [
    { label: 'Star — high volume, high margin', color: GOOD },
    { label: 'Fix — high volume, low margin', color: BAD },
    { label: 'Grow — low volume, high margin', color: PALETTE[0] },
    { label: 'Review — low volume, low margin', color: NEUTRAL },
  ]
  const withQuadrant = rows.map((p) => ({ ...p, quadrant: quadrantOf(p) }))
  const quadrantSummary = QUADRANTS.map((q) => {
    const members = withQuadrant.filter((p) => p.quadrant === q.label)
    const revenue = members.reduce((s, p) => s + p.revenue, 0)
    return {
      label: q.label,
      products: members.length,
      revenue,
      profit: members.reduce((s, p) => s + p.profit, 0),
      share: (revenue / rows.reduce((s, p) => s + p.revenue, 0)) * 100,
    }
  })

  return (
    <>
      <PageHeader title="Product analysis">
        What sells, what earns, and what gives margin away. {num(rows.length)}{' '}
        products in the current selection.
      </PageHeader>

      <div className="kpi-row">
        <Kpi label="Products" value={num(rows.length)} />
        <Kpi label="Units sold" value={num(rows.reduce((s, p) => s + p.units, 0))} />
        <Kpi label="Best margin" value={pct(Math.max(...margins), 1)} />
        <Kpi label="Worst margin" value={pct(Math.min(...margins), 1)} higherIsBetter={false} />
        <Kpi label="Median margin" value={pct(medianMargin, 1)} />
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Best sellers' && (
        <div className="grid grid-2">
          <Card title="Top 15 by units sold">
            <ChartFrame height={440}>
              <BarChart data={topUnits} layout="vertical"
                        margin={{ top: 6, right: 30, left: 4, bottom: 0 }}>
                <Grid />
                <XAxisStyled type="number" />
                <YAxis type="category" dataKey="product_id" width={78}
                       stroke="var(--text-faint)" fontSize={10}
                       tickLine={false} axisLine={false} />
                <TooltipStyled content={ProductTooltip} />
                <Bar dataKey="units" name="Units" fill={PALETTE[0]} radius={[0, 3, 3, 0]} />
              </BarChart>
            </ChartFrame>
          </Card>

          <Card
            title="Top 15 by revenue"
            note="The two lists differ, and the difference is the point: high unit volume in a cheap category is not the same business as high revenue in an expensive one, and they need different decisions."
          >
            <ChartFrame height={440}>
              <BarChart data={topRevenue} layout="vertical"
                        margin={{ top: 6, right: 30, left: 4, bottom: 0 }}>
                <Grid />
                <XAxisStyled type="number" tickFormatter={axisMoney} />
                <YAxis type="category" dataKey="product_id" width={78}
                       stroke="var(--text-faint)" fontSize={10}
                       tickLine={false} axisLine={false} />
                <TooltipStyled content={ProductTooltip} />
                <Bar dataKey="revenue" name="Revenue" fill={PALETTE[2]} radius={[0, 3, 3, 0]} />
              </BarChart>
            </ChartFrame>
          </Card>
        </div>
      )}

      {tab === 'Most profitable' && (
        <div className="grid grid-2">
          <Card title="Top 15 by absolute profit" note="Where the profit actually comes from.">
            <ChartFrame height={440}>
              <BarChart data={topProfit} layout="vertical"
                        margin={{ top: 6, right: 30, left: 4, bottom: 0 }}>
                <Grid />
                <XAxisStyled type="number" tickFormatter={axisMoney} />
                <YAxis type="category" dataKey="product_id" width={78}
                       stroke="var(--text-faint)" fontSize={10}
                       tickLine={false} axisLine={false} />
                <TooltipStyled content={ProductTooltip} />
                <Bar dataKey="profit" name="Profit" fill={PALETTE[2]} radius={[0, 3, 3, 0]} />
              </BarChart>
            </ChartFrame>
          </Card>

          <Card
            title="15 lowest-margin products"
            note="Anything at or below zero is being sold at a loss and needs a pricing or supply answer, not a sales one."
          >
            <ChartFrame height={440}>
              <BarChart data={worstMargin} layout="vertical"
                        margin={{ top: 6, right: 30, left: 4, bottom: 0 }}>
                <Grid />
                <XAxisStyled type="number" tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
                <YAxis type="category" dataKey="product_id" width={78}
                       stroke="var(--text-faint)" fontSize={10}
                       tickLine={false} axisLine={false} />
                <TooltipStyled content={ProductTooltip} />
                <ReferenceLine x={0} stroke={NEUTRAL} />
                <Bar dataKey="profit_margin_pct" name="Margin" radius={[0, 3, 3, 0]}>
                  {worstMargin.map((p) => (
                    <Cell key={p.product_id}
                          fill={(p.profit_margin_pct ?? 0) < 0 ? BAD : PALETTE[7]} />
                  ))}
                </Bar>
              </BarChart>
            </ChartFrame>
          </Card>
        </div>
      )}

      {tab === 'Discount-heavy' && (
        <Card
          title="Discount rate against margin — 20 heaviest discounters"
          note="Products where the discount bar approaches or exceeds the margin bar are giving away most of what they earn. Low-volume products are excluded so a single heavily discounted order cannot top the list."
        >
          <ChartFrame height={520}>
            <BarChart data={[...discountHeavy].reverse()} layout="vertical"
                      margin={{ top: 6, right: 24, left: 4, bottom: 0 }}>
              <Grid />
              <XAxisStyled type="number" tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
              <YAxis type="category" dataKey="product_id" width={78}
                     stroke="var(--text-faint)" fontSize={10}
                     tickLine={false} axisLine={false} />
              <TooltipStyled content={ProductTooltip} />
              <LegendStyled />
              <Bar dataKey="discount_rate_pct" name="Discount rate %" fill={PALETTE[1]}
                   radius={[0, 3, 3, 0]} />
              <Bar dataKey="profit_margin_pct" name="Margin %" fill={PALETTE[0]}
                   radius={[0, 3, 3, 0]} />
            </BarChart>
          </ChartFrame>

          <div className="mt">
            <DataTable
              scroll
              rowKey={(r) => r.product_id}
              rows={discountHeavy}
              columns={[
                { key: 'id', label: 'Product', render: (r) => <span className="mono">{r.product_id}</span> },
                { key: 'name', label: 'Name', render: (r) => r.product_name },
                { key: 'cat', label: 'Category', render: (r) => r.product_category },
                { key: 'units', label: 'Units', numeric: true, render: (r) => num(r.units) },
                { key: 'rev', label: 'Revenue', numeric: true, render: (r) => money(r.revenue, 2) },
                { key: 'disc', label: 'Discount rate', numeric: true, render: (r) => pct(r.discount_rate_pct, 2) },
                { key: 'margin', label: 'Margin', numeric: true, render: (r) => pct(r.profit_margin_pct, 2) },
              ]}
            />
          </div>
        </Card>
      )}

      {tab === 'Portfolio matrix' && (
        <>
          <Card
            title="Portfolio matrix: volume against margin"
            note={`Split at the medians (${num(medianUnits)} units, ${pct(medianMargin, 1)} margin). Fix is the priority quadrant — the volume is already proven, so margin recovered there needs no new demand. Grow is the opposite bet: the economics work, they just need volume.`}
          >
            <ChartFrame height={470}>
              <ScatterChart margin={{ top: 10, right: 16, left: 0, bottom: 10 }}>
                <Grid />
                <XAxisStyled type="number" dataKey="units" name="Units"
                             label={{ value: 'Units sold', position: 'insideBottom',
                                      offset: -4, fill: 'var(--text-faint)', fontSize: 11 }} />
                <YAxisStyled type="number" dataKey="profit_margin_pct" name="Margin"
                             width={50} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
                <ZAxis type="number" dataKey="revenue" range={[40, 460]} />
                <TooltipStyled cursor={{ strokeDasharray: '3 3' }} content={ProductTooltip} />
                <LegendStyled />
                <ReferenceLine x={medianUnits} stroke={NEUTRAL} strokeDasharray="4 4" />
                <ReferenceLine y={medianMargin} stroke={NEUTRAL} strokeDasharray="4 4" />
                {QUADRANTS.map((q) => (
                  <Scatter key={q.label} name={q.label}
                           data={withQuadrant.filter((p) => p.quadrant === q.label)}
                           fill={q.color} fillOpacity={0.75} />
                ))}
              </ScatterChart>
            </ChartFrame>
          </Card>

          <Card className="mt" title="Quadrant summary">
            <DataTable
              rowKey={(r) => r.label}
              rows={quadrantSummary}
              columns={[
                { key: 'q', label: 'Quadrant', render: (r) => r.label },
                { key: 'n', label: 'Products', numeric: true, render: (r) => num(r.products) },
                { key: 'rev', label: 'Revenue', numeric: true, render: (r) => money(r.revenue, 2) },
                { key: 'profit', label: 'Profit', numeric: true, render: (r) => money(r.profit, 2) },
                { key: 'share', label: 'Revenue share', numeric: true, render: (r) => pct(r.share, 1) },
              ]}
            />
          </Card>
        </>
      )}
    </>
  )
}
