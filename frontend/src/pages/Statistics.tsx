import { useState } from 'react'
import { Bar, BarChart, Cell, ReferenceLine, YAxis } from 'recharts'
import { api } from '../lib/api'
import type { HypothesisTest } from '../lib/api'
import { useApi } from '../lib/useApi'
import { moneyFull, num, pValue, pct } from '../lib/format'
import { BAD, GOOD, NEUTRAL, PALETTE } from '../lib/palette'
import { Card, DataTable, ErrorBox, Kpi, Loading, Note, PageHeader, Tabs } from '../components/ui'
import {
  ChartFrame,
  Grid,
  LegendStyled,
  TooltipStyled,
  XAxisStyled,
  YAxisStyled,
} from '../components/charts'

const TABS = ['Hypothesis tests', 'Correlations', 'Confidence intervals',
  'Regression', 'Time-series diagnostics']

function effectSize(test: HypothesisTest): { value: number | null; label: string } {
  const e = test.effect_size
  for (const key of ['cohens_d', 'cramers_v', 'eta_squared']) {
    if (typeof e[key] === 'number') {
      return { value: e[key] as number, label: key.replace(/_/g, ' ') }
    }
  }
  return { value: null, label: 'n/a' }
}

export default function Statistics() {
  const [tab, setTab] = useState(TABS[0])
  const stats = useApi(() => api.statistics(), [])
  const ts = useApi(() => api.timeseries(), [])

  if (stats.error) return <ErrorBox message={stats.error} />
  if (!stats.data) return <Loading />

  const s = stats.data
  const anova = s.hypothesis_tests.find((t) => t.name === 'regions_anova')
  const weekend = s.hypothesis_tests.find((t) => t.name === 'weekend_effect')
  const regionTest = s.hypothesis_tests.find((t) => t.name === 'region_order_value')
  const lagged = s.correlations_monthly_level.find((c) => c.question.includes('FOLLOWING'))
  const varianceExplained =
    (anova?.effect_size?.variance_explained_pct as number | undefined) ?? 0

  return (
    <>
      <PageHeader title="Statistical analysis">
        Separating description from inference. A dashboard can show that
        high-discount orders have a lower margin; only a test can say whether
        that gap is larger than sampling noise, how big it is, and whether it
        survives controlling for product mix.
      </PageHeader>

      <Note kind="info">
        Computed on the full unfiltered dataset (n = {num(s.n_transactions)}) by{' '}
        <code>src/stats_analysis.py</code>, at alpha = {s.alpha}. Sidebar filters
        do not apply — re-running the tests for every filter combination would
        be p-hacking by interface.
      </Note>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Hypothesis tests' && (
        <>
          <Note kind="warn">
            <strong>Read the effect size, not the p-value.</strong> With{' '}
            {num(s.n_transactions)} transactions almost any difference clears
            p &lt; 0.05, so significance here is nearly free. What separates a
            finding worth acting on from a statistical curiosity is how large the
            effect actually is.
          </Note>

          {s.hypothesis_tests.map((test) => {
            const effect = effectSize(test)
            const magnitude = String(test.effect_size.magnitude ?? 'n/a')
            const marker = !test.significant
              ? '○'
              : ['medium', 'large'].includes(magnitude)
                ? '●'
                : '◐'
            const markerColor = !test.significant
              ? NEUTRAL
              : ['medium', 'large'].includes(magnitude)
                ? BAD
                : PALETTE[1]

            return (
              <details key={test.name}>
                <summary>
                  <span style={{ color: markerColor, fontSize: '1.1em' }}>{marker}</span>
                  {test.question}
                </summary>
                <div className="details-body">
                  <div className="kpi-row">
                    <Kpi label="p-value" value={pValue(test.p_value)} />
                    <Kpi label={effect.label}
                         value={effect.value !== null ? effect.value.toFixed(4) : '—'}
                         hint={`Magnitude: ${magnitude}`} />
                    <Kpi label="Magnitude" value={magnitude} />
                    <Kpi label="Decision"
                         value={test.significant ? 'Reject H₀' : 'Fail to reject'} />
                  </div>

                  <p><strong>H₀:</strong> {test.null_hypothesis}</p>
                  <p><strong>H₁:</strong> {test.alternative_hypothesis}</p>
                  <p>
                    <strong>Test:</strong> {test.test}<br />
                    <strong>Statistic:</strong> {test.statistic}
                  </p>

                  {typeof test.assumptions?.note === 'string' && (
                    <p className="small muted">
                      <strong>Assumptions:</strong> {test.assumptions.note}
                    </p>
                  )}

                  {(() => {
                    const agreeKey = Object.keys(test.robustness ?? {}).find((k) =>
                      k.includes('agree'),
                    )
                    if (!agreeKey) return null
                    const agrees = Boolean(test.robustness[agreeKey])
                    return (
                      <p className="small muted">
                        <strong>Robustness:</strong> the non-parametric
                        cross-check{' '}
                        <span className={agrees ? 'pos' : 'neg'}>
                          {agrees ? 'agrees' : 'DISAGREES'}
                        </span>{' '}
                        with the parametric test.
                        {agrees
                          ? ' Agreement between the two is the evidence.'
                          : ' Treat this result with care.'}
                      </p>
                    )
                  })()}

                  <Note kind={test.significant ? 'warn' : 'info'}>{test.interpretation}</Note>
                </div>
              </details>
            )
          })}

          <Card className="mt" title="All tests">
            <DataTable
              rowKey={(t) => t.name}
              rows={s.hypothesis_tests}
              columns={[
                { key: 'name', label: 'Test', render: (t) => t.name.replace(/_/g, ' ') },
                { key: 'method', label: 'Method', render: (t) => t.test.split('(')[0].trim() },
                { key: 'p', label: 'p-value', numeric: true, render: (t) => pValue(t.p_value) },
                {
                  key: 'effect', label: 'Effect size', numeric: true,
                  render: (t) => {
                    const e = effectSize(t)
                    return e.value !== null ? e.value.toFixed(4) : '—'
                  },
                },
                { key: 'mag', label: 'Magnitude',
                  render: (t) => String(t.effect_size.magnitude ?? '—') },
                {
                  key: 'decision', label: 'Decision',
                  render: (t) => (
                    <span className={`badge ${t.significant ? 'medium' : 'low'}`}>
                      {t.significant ? 'Reject H₀' : 'Fail to reject'}
                    </span>
                  ),
                },
              ]}
            />
          </Card>

          <Card className="mt" title="Reading these results honestly">
            <ol className="small" style={{ paddingLeft: 20, lineHeight: 1.7 }}>
              <li>
                <strong>Significance is nearly free at this sample size.</strong>{' '}
                The regional order-value comparison is the clearest case: it is
                significant at p = {pValue(regionTest?.p_value)}, yet region
                explains only {varianceExplained.toFixed(2)}% of the variance in
                order value. <em>Statistically real, commercially irrelevant.</em>
              </li>
              <li>
                <strong>Not every test rejects.</strong> The weekend/weekday
                comparison returns p = {pValue(weekend?.p_value)} — no
                significant difference. It is reported because a battery of tests
                that all reject is usually a sign of a badly specified battery,
                not a remarkable business.
              </li>
              <li>
                <strong>Marketing's lagged effect is not established.</strong>{' '}
                See the Correlations tab.
              </li>
            </ol>
          </Card>
        </>
      )}

      {tab === 'Correlations' && (
        <div className="stack">
          <Card
            title="Pearson against Spearman — transaction level"
            note="Both are shown deliberately. Pearson asks whether the relationship is linear; Spearman asks whether it is monotonic. A wide gap between the two bars means the relationship is real but curved — which changes what a linear rule of thumb would get wrong."
          >
            <ChartFrame height={340}>
              <BarChart data={s.correlations_transaction_level} layout="vertical"
                        margin={{ top: 8, right: 20, left: 4, bottom: 4 }}>
                <Grid />
                <XAxisStyled type="number" domain={[-1, 1]} />
                <YAxis type="category" dataKey="pair" width={210}
                       stroke="var(--text-faint)" fontSize={10}
                       tickLine={false} axisLine={false} />
                <TooltipStyled formatter={(v: number) => v.toFixed(4)} />
                <LegendStyled />
                <ReferenceLine x={0} stroke={NEUTRAL} />
                <Bar dataKey="pearson_r" name="Pearson r" fill={PALETTE[0]} radius={[0, 2, 2, 0]} />
                <Bar dataKey="spearman_rho" name="Spearman ρ" fill={PALETTE[1]} radius={[0, 2, 2, 0]} />
              </BarChart>
            </ChartFrame>
          </Card>

          <Card title="Transaction-level detail">
            <DataTable
              rowKey={(c) => c.pair}
              rows={s.correlations_transaction_level}
              columns={[
                { key: 'pair', label: 'Pair', render: (c) => <span className="mono">{c.pair}</span> },
                { key: 'q', label: 'Question',
                  render: (c) => <span style={{ whiteSpace: 'normal' }}>{c.question}</span> },
                { key: 'r', label: 'Pearson r', numeric: true, render: (c) => c.pearson_r.toFixed(3) },
                { key: 'rho', label: 'Spearman ρ', numeric: true, render: (c) => c.spearman_rho.toFixed(3) },
                { key: 'p', label: 'p', numeric: true, render: (c) => pValue(c.pearson_p) },
                { key: 'r2', label: 'R²', numeric: true, render: (c) => c.r_squared.toFixed(3) },
                { key: 'strength', label: 'Strength', render: (c) => c.strength },
              ]}
            />
          </Card>

          <Card title="Monthly-level correlations">
            <DataTable
              rowKey={(c) => c.pair}
              rows={s.correlations_monthly_level}
              columns={[
                { key: 'pair', label: 'Pair', render: (c) => <span className="mono">{c.pair}</span> },
                { key: 'q', label: 'Question',
                  render: (c) => <span style={{ whiteSpace: 'normal' }}>{c.question}</span> },
                { key: 'n', label: 'n', numeric: true, render: (c) => c.n },
                { key: 'r', label: 'Pearson r', numeric: true, render: (c) => c.pearson_r.toFixed(3) },
                { key: 'p', label: 'p', numeric: true, render: (c) => pValue(c.pearson_p) },
                { key: 'strength', label: 'Strength', render: (c) => c.strength },
              ]}
            />
          </Card>

          {lagged && (
            <Note kind="warn">
              <strong>Marketing effectiveness is not established by this
              analysis.</strong> Same-month spend correlates strongly with
              revenue, but marketing budgets are set as a percentage of revenue,
              so that correlation largely runs backwards. Tested properly against
              the <em>following</em> month's revenue the coefficient is{' '}
              {lagged.pearson_r.toFixed(3)} at p = {pValue(lagged.pearson_p)} —
              it does not clear the threshold.
            </Note>
          )}
        </div>
      )}

      {tab === 'Confidence intervals' && (
        <div className="stack">
          <Card
            title={`${(s.confidence_level * 100).toFixed(0)}% confidence intervals`}
            note="Where a metric appears twice, the parametric and bootstrap intervals are both shown. Their agreement is the check that the central limit theorem is doing its job at this sample size; disagreement would mean the parametric interval should not be trusted."
          >
            <DataTable
              rowKey={(c, i) => `${c.metric}-${i}`}
              rows={s.confidence_intervals}
              columns={[
                { key: 'metric', label: 'Metric', render: (c) => c.metric },
                { key: 'n', label: 'n', numeric: true, render: (c) => num(c.n) },
                {
                  key: 'est', label: 'Estimate', numeric: true,
                  render: (c) =>
                    Math.abs(c.point_estimate) < 10
                      ? c.point_estimate.toFixed(5)
                      : moneyFull(c.point_estimate),
                },
                {
                  key: 'ci', label: 'Interval', numeric: true,
                  render: (c) =>
                    Math.abs(c.point_estimate) < 10
                      ? `[${c.ci_low.toFixed(5)}, ${c.ci_high.toFixed(5)}]`
                      : `[${moneyFull(c.ci_low)}, ${moneyFull(c.ci_high)}]`,
                },
                { key: 'method', label: 'Method', render: (c) => c.method },
                { key: 'note', label: 'Note',
                  render: (c) => <span style={{ whiteSpace: 'normal' }}>{c.note}</span> },
              ]}
            />
          </Card>
        </div>
      )}

      {tab === 'Regression' && (
        <div className="stack">
          <Card title="Explanatory regression">
            <div className="kpi-row">
              <Kpi label="R²" value={s.regression.r_squared.toFixed(4)} />
              <Kpi label="Adjusted R²" value={s.regression.adj_r_squared.toFixed(4)} />
              <Kpi label="Observations" value={num(s.regression.n_observations)} />
              <Kpi label="Discount coefficient"
                   value={s.regression.discount_coefficient.toFixed(4)}
                   hint="Percentage points of margin per percentage point of discount, holding the controls constant." />
            </div>
            <p className="small muted">
              <strong>Model:</strong> <code>{s.regression.model}</code>
              <br />
              <strong>Standard errors:</strong> {s.regression.standard_errors}
            </p>
            <Note kind="warn">{s.regression.interpretation}</Note>
          </Card>

          <Card
            title="Continuous predictors"
            note="Category, segment, region and year fixed effects are fitted but not plotted — they are controls, not findings. Their job is to stop the discount coefficient absorbing the fact that discounted orders skew toward thin-margin categories."
          >
            {(() => {
              const main = s.regression.coefficients.filter(
                (c) => !c.term.startsWith('C(') && c.term !== 'Intercept',
              )
              return (
                <ChartFrame height={260}>
                  <BarChart data={main} layout="vertical"
                            margin={{ top: 8, right: 20, left: 4, bottom: 4 }}>
                    <Grid />
                    <XAxisStyled type="number" />
                    <YAxis type="category" dataKey="term" width={130}
                           stroke="var(--text-faint)" fontSize={11}
                           tickLine={false} axisLine={false} />
                    <TooltipStyled formatter={(v: number) => v.toFixed(4)} />
                    <ReferenceLine x={0} stroke={NEUTRAL} />
                    <Bar dataKey="coefficient" name="Coefficient" radius={[0, 3, 3, 0]}>
                      {main.map((c) => (
                        <Cell key={c.term} fill={c.coefficient < 0 ? BAD : GOOD} />
                      ))}
                    </Bar>
                  </BarChart>
                </ChartFrame>
              )
            })()}
          </Card>

          <Card title="Full coefficient table">
            <DataTable
              scroll
              rowKey={(c) => c.term}
              rows={s.regression.coefficients}
              columns={[
                { key: 'term', label: 'Term', render: (c) => <span className="mono">{c.term}</span> },
                { key: 'coef', label: 'Coefficient', numeric: true, render: (c) => c.coefficient.toFixed(4) },
                { key: 'se', label: 'Std error', numeric: true, render: (c) => c.std_error.toFixed(4) },
                { key: 'p', label: 'p', numeric: true, render: (c) => pValue(c.p_value) },
                {
                  key: 'sig', label: 'Significant',
                  render: (c) => (
                    <span className={`badge ${c.significant ? 'medium' : 'low'}`}>
                      {c.significant ? 'yes' : 'no'}
                    </span>
                  ),
                },
              ]}
            />
            <p className="small faint mt">
              This is a descriptive regression — a variance decomposition, not a
              predictive model. It reports coefficients and R², not out-of-sample
              error, because the question is <em>how much of margin variation is
              attributable to discount</em>, not <em>what will margin be next
              month</em>.
            </p>
          </Card>
        </div>
      )}

      {tab === 'Time-series diagnostics' && (
        <div className="stack">
          {!ts.data ? (
            <Loading />
          ) : (
            <>
              <div className="kpi-row">
                <Kpi label="CAGR" value={pct(ts.data.trend.cagr_pct)} />
                <Kpi label="Trend R²" value={ts.data.trend.r_squared.toFixed(3)} />
                <Kpi label="Seasonal strength"
                     value={ts.data.seasonality.seasonal_strength.toFixed(3)} />
                <Kpi label="ACF at lag 12"
                     value={ts.data.diagnostics.acf_lag_12.toFixed(3)} />
              </div>

              <Note kind="info">{ts.data.trend.interpretation}</Note>
              <Note kind="info">{ts.data.seasonality.interpretation}</Note>

              <Card
                title="Autocorrelation function of log revenue"
                note="The bump at lag 12 is the annual seasonal cycle expressed numerically: this month resembles the same month last year more than it resembles last month."
              >
                <ChartFrame height={280}>
                  <BarChart
                    data={ts.data.diagnostics.acf.map((v, lag) => ({ lag, acf: v }))}
                    margin={{ top: 8, right: 8, left: 0, bottom: 4 }}
                  >
                    <Grid />
                    <XAxisStyled dataKey="lag"
                                 label={{ value: 'Lag (months)', position: 'insideBottom',
                                          offset: -2, fill: 'var(--text-faint)', fontSize: 11 }} />
                    <YAxisStyled width={48} />
                    <TooltipStyled formatter={(v: number) => v.toFixed(4)}
                                   labelFormatter={(l: number) => `Lag ${l}`} />
                    <ReferenceLine y={0} stroke={NEUTRAL} />
                    <Bar dataKey="acf" name="Autocorrelation" fill={PALETTE[0]}
                         radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ChartFrame>
              </Card>

              <Card
                title="Stationarity tests"
                note="ADF and KPSS test opposite nulls, which is why both are run: ADF's null is 'has a unit root', KPSS's null is 'is stationary'. Agreement between them is a far stronger statement about the series' structure than either could make alone."
              >
                <DataTable
                  rowKey={(r) => r.test}
                  rows={[
                    {
                      test: 'ADF on log revenue',
                      statistic: ts.data.diagnostics.adf_on_log_revenue.statistic,
                      p: ts.data.diagnostics.adf_on_log_revenue.p_value,
                      nullHypothesis: 'has a unit root (non-stationary)',
                      stationary: ts.data.diagnostics.adf_on_log_revenue.stationary_at_5pct,
                    },
                    {
                      test: 'KPSS on log revenue',
                      statistic: ts.data.diagnostics.kpss_on_log_revenue.statistic,
                      p: ts.data.diagnostics.kpss_on_log_revenue.p_value,
                      nullHypothesis: 'is trend-stationary',
                      stationary: ts.data.diagnostics.kpss_on_log_revenue.stationary_at_5pct,
                    },
                    {
                      test: 'ADF on first difference',
                      statistic: ts.data.diagnostics.adf_on_first_difference.statistic,
                      p: ts.data.diagnostics.adf_on_first_difference.p_value,
                      nullHypothesis: 'has a unit root (non-stationary)',
                      stationary: ts.data.diagnostics.adf_on_first_difference.stationary_at_5pct,
                    },
                  ]}
                  columns={[
                    { key: 'test', label: 'Test', render: (r) => r.test },
                    { key: 'stat', label: 'Statistic', numeric: true, render: (r) => r.statistic.toFixed(3) },
                    { key: 'p', label: 'p-value', numeric: true, render: (r) => pValue(r.p) },
                    { key: 'null', label: 'Null hypothesis', render: (r) => r.nullHypothesis },
                    {
                      key: 'stationary', label: 'Stationary at 5%',
                      render: (r) => (
                        <span className={`badge ${r.stationary ? 'good' : 'low'}`}>
                          {r.stationary ? 'yes' : 'no'}
                        </span>
                      ),
                    },
                  ]}
                />
                <p className="small muted mt">{ts.data.diagnostics.interpretation}</p>
              </Card>

              <Card
                title="Growth decomposition"
                note={ts.data.growth_decomposition.interpretation}
              >
                <DataTable
                  rowKey={(r) => String(r.year)}
                  rows={ts.data.growth_decomposition.by_year}
                  columns={[
                    { key: 'y', label: 'Year', render: (r) => r.year },
                    { key: 'rev', label: 'Revenue growth', numeric: true,
                      render: (r) => pct(r.revenue_growth_pct, 2) },
                    { key: 'vol', label: 'Volume growth', numeric: true,
                      render: (r) => pct(r.volume_growth_pct, 2) },
                    { key: 'aov', label: 'Order value growth', numeric: true,
                      render: (r) => pct(r.order_value_growth_pct, 2) },
                    { key: 'volc', label: 'From volume', numeric: true,
                      render: (r) => pct(r.volume_contribution_pct, 0) },
                    { key: 'aovc', label: 'From order value', numeric: true,
                      render: (r) => pct(r.order_value_contribution_pct, 0) },
                  ]}
                />
              </Card>
            </>
          )}
        </div>
      )}
    </>
  )
}
