import {
  Bar,
  BarChart,
  ComposedChart,
  Cell,
  Line,
  ReferenceLine,
  YAxis,
} from 'recharts'
import { api } from '../lib/api'
import type { Filters } from '../lib/api'
import { useApi } from '../lib/useApi'
import { axisMoney, money, num, pct, shortMonth, signedPct } from '../lib/format'
import { BAD, GOOD, NEUTRAL, PALETTE } from '../lib/palette'
import { Card, ErrorBox, Kpi, Loading, Note, PageHeader } from '../components/ui'
import {
  ChartFrame,
  Grid,
  LegendStyled,
  TooltipStyled,
  XAxisStyled,
  YAxisStyled,
  makeTooltip,
} from '../components/charts'

function growth(current: number | undefined, prior: number | undefined): number | null {
  if (current === undefined || prior === undefined || !prior) return null
  return ((current - prior) / Math.abs(prior)) * 100
}

export default function Executive({ filters }: { filters: Filters }) {
  const kpis = useApi(() => api.kpis(filters), [filters])
  const monthly = useApi(() => api.monthly(filters), [filters])
  const yearly = useApi(() => api.yearly(filters), [filters])
  const regions = useApi(() => api.breakdown('region', filters), [filters])

  if (kpis.error) return <ErrorBox message={kpis.error} />
  if (!kpis.data || !monthly.data || !yearly.data || !regions.data) return <Loading />

  const t = kpis.data.totals
  const ttm = kpis.data.ttm
  const prior = kpis.data.prior_ttm

  const ttmMargin =
    ttm.revenue && ttm.profit ? (ttm.profit / ttm.revenue) * 100 : undefined
  const priorMargin =
    prior.revenue && prior.profit ? (prior.profit / prior.revenue) * 100 : undefined

  const months = monthly.data
  const yoy = months.filter((m) => m.revenue_yoy_pct !== null)
  const regionRows = [...regions.data].sort((a, b) => a.revenue - b.revenue)

  const revenueTooltip = makeTooltip(
    (label) => shortMonth(label),
    {
      revenue: (v) => money(v, 2),
      revenue_ma3: (v) => money(v, 2),
      profit: (v) => money(v, 2),
      profit_margin_pct: (v) => pct(v, 2),
    },
  )

  return (
    <>
      <PageHeader title="Executive overview">
        {filters.start} to {filters.end} · {num(t.transactions)} transactions ·{' '}
        {kpis.data.comparison_basis}
      </PageHeader>

      <div className="kpi-row">
        <Kpi label="Revenue" value={money(t.revenue)}
             delta={growth(ttm.revenue, prior.revenue)}
             hint="Net revenue after discount." />
        <Kpi label="Gross profit" value={money(t.profit)}
             delta={growth(ttm.profit, prior.profit)}
             hint="Net revenue less cost of goods sold." />
        <Kpi label="Gross margin" value={pct(t.gross_margin_pct, 2)}
             delta={ttmMargin !== undefined && priorMargin !== undefined
               ? ttmMargin - priorMargin : null}
             deltaSuffix=" pp"
             hint="Gross profit as a share of net revenue." />
        <Kpi label="Cost of goods" value={money(t.cost)}
             delta={growth(ttm.cost, prior.cost)} higherIsBetter={false}
             hint="Quantity x unit cost. A rise here is unfavourable." />
        <Kpi label="Transactions" value={num(t.transactions)}
             delta={growth(ttm.transactions, prior.transactions)} />
        <Kpi label="Customers" value={num(t.customers)}
             delta={growth(ttm.customers, prior.customers)} />
        <Kpi label="Avg order value" value={money(t.avg_order_value, 0)}
             hint="Net revenue divided by transaction count." />
        <Kpi label="Discount rate" value={pct(t.discount_rate_pct, 2)}
             higherIsBetter={false}
             hint="Discount given as a share of gross list-price revenue." />
      </div>

      <div className="grid grid-2-1 mb">
        <Card
          title="Revenue and 3-month moving average"
          note="The moving average strips out the month-to-month seasonal swing so the underlying growth path is visible. Where bars sit well below the line, something other than seasonality was happening."
        >
          <ChartFrame height={300}>
            <ComposedChart data={months} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              <Grid />
              <XAxisStyled dataKey="month_start" tickFormatter={shortMonth} minTickGap={26} />
              <YAxisStyled tickFormatter={axisMoney} />
              <TooltipStyled content={revenueTooltip} />
              <LegendStyled />
              <Bar dataKey="revenue" name="Monthly revenue" fill={PALETTE[0]}
                   fillOpacity={0.55} radius={[2, 2, 0, 0]} />
              <Line type="monotone" dataKey="revenue_ma3" name="3-month moving average"
                    stroke={PALETTE[1]} strokeWidth={2.6} dot={false} />
            </ComposedChart>
          </ChartFrame>
        </Card>

        <Card
          title="Revenue by region"
          note="Compare with the margin column on the Profitability page — the largest regions are not the most profitable ones."
        >
          <ChartFrame height={300}>
            <BarChart data={regionRows} layout="vertical"
                      margin={{ top: 6, right: 46, left: 4, bottom: 0 }}>
              <Grid />
              <XAxisStyled type="number" tickFormatter={axisMoney} />
              <YAxis type="category" dataKey="name" width={96}
                     stroke="var(--text-faint)" fontSize={11}
                     tickLine={false} axisLine={false} />
              <TooltipStyled
                formatter={(v: number) => money(v, 2)}
                labelFormatter={(l: string) => l}
              />
              <Bar dataKey="revenue" name="Revenue" fill={PALETTE[0]} radius={[0, 3, 3, 0]} />
            </BarChart>
          </ChartFrame>
        </Card>
      </div>

      <Card
        title="Gross profit and gross margin"
        note="The critical chart in this dashboard: profit rises while the margin line drifts down. Growth is being bought with margin — the Profitability page decomposes where it is going."
      >
        <ChartFrame height={320}>
          <ComposedChart data={months} margin={{ top: 6, right: 12, left: 0, bottom: 0 }}>
            <Grid />
            <XAxisStyled dataKey="month_start" tickFormatter={shortMonth} minTickGap={26} />
            <YAxisStyled yAxisId="left" tickFormatter={axisMoney} />
            <YAxisStyled yAxisId="right" orientation="right" width={48}
                         tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
            <TooltipStyled content={revenueTooltip} />
            <LegendStyled />
            <Bar yAxisId="left" dataKey="profit" name="Gross profit" fill={PALETTE[2]}
                 fillOpacity={0.6} radius={[2, 2, 0, 0]} />
            <Line yAxisId="right" type="monotone" dataKey="profit_margin_pct"
                  name="Gross margin %" stroke={BAD} strokeWidth={2.4}
                  dot={{ r: 2.2 }} />
          </ComposedChart>
        </ChartFrame>
      </Card>

      <div className="grid grid-2 mt">
        <Card
          title="Revenue, cost and profit by year"
          note="Cost bars grow faster than revenue bars — the mechanical cause of the margin decline."
        >
          <ChartFrame height={290}>
            <BarChart data={yearly.data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              <Grid />
              <XAxisStyled dataKey="year" />
              <YAxisStyled tickFormatter={axisMoney} />
              <TooltipStyled formatter={(v: number) => money(v, 2)} />
              <LegendStyled />
              <Bar dataKey="revenue" name="Revenue" fill={PALETTE[0]} radius={[3, 3, 0, 0]} />
              <Bar dataKey="cost" name="Cost" fill={PALETTE[7]} radius={[3, 3, 0, 0]} />
              <Bar dataKey="profit" name="Profit" fill={PALETTE[2]} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ChartFrame>
        </Card>

        <Card
          title="Year-on-year revenue growth"
          note="Each month against the same month a year earlier, so the seasonal cycle cancels out. Negative bars are genuine contractions, not calendar effects."
        >
          {yoy.length === 0 ? (
            <Note kind="info">
              Year-on-year growth needs at least 13 months inside the current
              filter.
            </Note>
          ) : (
            <ChartFrame height={290}>
              <BarChart data={yoy} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                <Grid />
                <XAxisStyled dataKey="month_start" tickFormatter={shortMonth} minTickGap={26} />
                <YAxisStyled width={48} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
                <TooltipStyled
                  formatter={(v: number) => signedPct(v, 2)}
                  labelFormatter={(l: string) => shortMonth(l)}
                />
                <ReferenceLine y={0} stroke={NEUTRAL} />
                <Bar dataKey="revenue_yoy_pct" name="YoY growth" radius={[2, 2, 0, 0]}>
                  {yoy.map((row) => (
                    <Cell
                      key={row.month_start}
                      fill={(row.revenue_yoy_pct ?? 0) >= 0 ? GOOD : BAD}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ChartFrame>
          )}
        </Card>
      </div>
    </>
  )
}
