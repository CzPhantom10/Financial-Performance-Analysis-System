/* Typed access to the FastAPI backend.
 *
 * Every filtered endpoint takes the same filter object, so the query-string
 * construction lives in one place: a page never assembles a URL by hand, which
 * is what keeps "the filter applies everywhere" true rather than aspirational.
 */

export interface Filters {
  start: string
  end: string
  regions: string[]
  categories: string[]
  segments: string[]
}

export interface Meta {
  date_range: { start: string; end: string }
  transactions: number
  regions: string[]
  categories: string[]
  segments: string[]
}

export interface Totals {
  transactions: number
  customers: number
  units: number
  revenue: number
  gross_revenue: number
  discount_amount: number
  cost: number
  profit: number
  loss_making: number
  gross_margin_pct: number | null
  cost_to_revenue_pct: number | null
  discount_rate_pct: number | null
  avg_order_value: number | null
  revenue_per_customer: number | null
  loss_making_pct: number | null
}

export interface KpiResponse {
  totals: Totals
  ttm: Partial<Totals>
  prior_ttm: Partial<Totals>
  comparison_basis: string
}

export interface MonthPoint {
  month_start: string
  year_month: string
  year: number
  revenue: number
  cost: number
  profit: number
  transactions: number
  units: number
  customers: number
  profit_margin_pct: number | null
  cost_to_revenue_pct: number | null
  discount_rate_pct: number | null
  avg_order_value: number | null
  revenue_ma3: number | null
  revenue_mom_pct: number | null
  revenue_yoy_pct: number | null
  cumulative_revenue: number
}

export interface YearPoint {
  year: number
  revenue: number
  cost: number
  profit: number
  transactions: number
  customers: number
  gross_margin_pct: number | null
  avg_order_value: number | null
  revenue_growth_pct: number | null
  cost_growth_pct: number | null
  profit_growth_pct: number | null
  volume_growth_pct: number | null
}

export interface BreakdownRow {
  name: string
  transactions: number
  customers: number
  units: number
  revenue: number
  cost: number
  profit: number
  profit_margin_pct: number | null
  pct_of_revenue: number | null
  pct_of_profit: number | null
  avg_order_value: number | null
  discount_rate_pct: number | null
}

export interface DiscountBand {
  band: string
  band_order: number
  transactions: number
  avg_quantity: number
  gross_revenue: number
  discount_given: number
  revenue: number
  profit: number
  profit_margin_pct: number | null
  avg_order_value: number
  loss_making: number
  pct_of_revenue: number | null
}

export interface ProductRow {
  product_id: string
  product_name: string
  product_category: string
  transactions: number
  units: number
  revenue: number
  cost: number
  profit: number
  gross_revenue: number
  discount_amount: number
  profit_margin_pct: number | null
  discount_rate_pct: number | null
  avg_realised_price: number | null
  revenue_percentile: number
  margin_percentile: number
}

export interface CustomerRow {
  rank: number
  customer_id: string
  customer_segment: string
  region: string
  orders: number
  active_months: number
  revenue: number
  profit: number
  profit_margin_pct: number | null
  avg_order_value: number | null
  discount_rate_pct: number | null
  pct_of_revenue: number
  cumulative_pct: number
}

export interface CustomerResponse {
  top: CustomerRow[]
  deciles: {
    decile: number
    customers: number
    revenue: number
    profit: number
    avg_revenue: number
    pct_of_revenue: number
    cumulative_pct: number
  }[]
  order_bands: {
    band: string
    band_order: number
    customers: number
    revenue: number
    avg_lifetime_revenue: number
    avg_orders: number
    pct_of_customers: number
    pct_of_revenue: number
  }[]
  lorenz: { customer_pct: number; revenue_pct: number }[]
  summary: { customers: number; transactions: number; revenue: number }
  unattributed: { transactions: number; revenue: number | null }
}

export interface AnomalyRow {
  period: string
  scope: string
  metric: string
  method: string
  actual: number
  expected: number
  expected_low: number
  expected_high: number
  deviation: number
  deviation_pct: number
  score: number
  severity: 'Critical' | 'High' | 'Medium' | 'Low'
  material: boolean
  interpretation: string
}

export interface AnomalyResponse {
  thresholds: Record<string, number>
  total_anomalies: number
  by_severity: Record<string, number>
  material_flags: number
  immaterial_flags: number
  by_method: Record<string, number>
  rows: AnomalyRow[]
  materiality_threshold_pct: number
  ground_truth_scoring: {
    available: boolean
    events_injected?: number
    events_recovered?: number
    recall_pct?: number
    note?: string
    events?: {
      event_id: string
      kind: string
      window: string
      scope: unknown
      description: string
      detected: boolean
      n_matching_flags: number
    }[]
  }
}

export interface StatsResponse {
  alpha: number
  confidence_level: number
  n_transactions: number
  correlations_transaction_level: CorrelationRow[]
  correlations_monthly_level: CorrelationRow[]
  hypothesis_tests: HypothesisTest[]
  regression: Regression
  confidence_intervals: IntervalRow[]
}

export interface CorrelationRow {
  pair: string
  question: string
  n: number
  pearson_r: number
  pearson_p: number
  spearman_rho: number
  spearman_p: number
  r_squared: number
  strength: string
  linear_vs_monotonic_gap: number
}

export interface HypothesisTest {
  name: string
  question: string
  null_hypothesis: string
  alternative_hypothesis: string
  test: string
  statistic: number
  p_value: number
  effect_size: Record<string, unknown>
  groups: Record<string, unknown>
  assumptions: Record<string, unknown>
  robustness: Record<string, unknown>
  alpha: number
  interpretation: string
  significant: boolean
  decision: string
}

export interface Regression {
  model: string
  n_observations: number
  r_squared: number
  adj_r_squared: number
  f_statistic: number
  f_p_value: number
  standard_errors: string
  discount_coefficient: number
  discount_p_value: number
  coefficients: {
    term: string
    coefficient: number
    std_error: number
    p_value: number
    significant: boolean
  }[]
  interpretation: string
}

export interface IntervalRow {
  metric: string
  n: number
  point_estimate: number
  ci_low: number
  ci_high: number
  method: string
  confidence: number
  note: string
  margin_of_error: number
}

export interface TimeSeriesResponse {
  period: { start: string; end: string; months: number }
  trend: {
    cagr_pct: number
    implied_annual_growth_pct: number
    r_squared: number
    slope_p_value: number
    kendall_tau: number
    interpretation: string
  }
  seasonality: {
    seasonal_strength: number
    trend_strength: number
    peak_month: string
    trough_month: string
    peak_pct_above_average: number
    trough_pct_below_average: number
    peak_to_trough_ratio: number
    seasonal_index: {
      month: number
      month_name: string
      seasonal_index: number
      pct_vs_average: number
    }[]
    interpretation: string
  }
  diagnostics: {
    adf_on_log_revenue: { statistic: number; p_value: number; stationary_at_5pct: boolean }
    kpss_on_log_revenue: { statistic: number; p_value: number; stationary_at_5pct: boolean }
    adf_on_first_difference: { statistic: number; p_value: number; stationary_at_5pct: boolean }
    acf: number[]
    acf_lag_12: number
    interpretation: string
  }
  growth_decomposition: {
    by_year: {
      year: number
      revenue_growth_pct: number
      volume_growth_pct: number
      order_value_growth_pct: number
      volume_contribution_pct: number
      order_value_contribution_pct: number
    }[]
    interpretation: string
  }
}

export interface DataQualityResponse {
  summary: {
    raw_rows: number
    clean_rows: number
    rejected_rows: number
    rows_removed_as_duplicates: number
    retention_rate_pct: number
    rows_with_reconciliation_error: number
    date_range: string[]
    total_revenue: number
    gross_margin_pct: number
    rejection_reasons: Record<string, number>
  }
  steps: { step: string; detail: string; rows_affected: number }[]
}

export interface SqlQuery {
  name: string
  description: string
  sql: string
}

export interface SqlResult {
  name: string
  description: string
  sql: string
  columns: string[]
  row_count: number
  truncated: boolean
  rows: Record<string, unknown>[]
}

/* --------------------------------------------------------------------- */

function toQuery(filters?: Filters, extra?: Record<string, string | number>): string {
  const params = new URLSearchParams()
  if (filters) {
    if (filters.start) params.set('start', filters.start)
    if (filters.end) params.set('end', filters.end)
    // Repeated keys rather than a comma-joined string: FastAPI parses
    // ?regions=A&regions=B straight into a list, and a region containing a
    // comma would corrupt the joined form.
    filters.regions.forEach((r) => params.append('regions', r))
    filters.categories.forEach((c) => params.append('categories', c))
    filters.segments.forEach((s) => params.append('segments', s))
  }
  if (extra) {
    Object.entries(extra).forEach(([k, v]) => params.set(k, String(v)))
  }
  const s = params.toString()
  return s ? `?${s}` : ''
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
    } catch {
      /* response body was not JSON; the status line is all we have */
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export const api = {
  meta: () => get<Meta>('/api/meta'),
  kpis: (f: Filters) => get<KpiResponse>(`/api/kpis${toQuery(f)}`),
  monthly: (f: Filters) => get<MonthPoint[]>(`/api/monthly${toQuery(f)}`),
  yearly: (f: Filters) => get<YearPoint[]>(`/api/yearly${toQuery(f)}`),
  regionMonthly: (f: Filters) =>
    get<{ region: string; month_start: string; year_month: string; revenue: number; profit: number; profit_margin_pct: number | null }[]>(
      `/api/region-monthly${toQuery(f)}`,
    ),
  breakdown: (dimension: string, f: Filters) =>
    get<BreakdownRow[]>(`/api/breakdown/${dimension}${toQuery(f)}`),
  discountBands: (f: Filters) => get<DiscountBand[]>(`/api/discount-bands${toQuery(f)}`),
  products: (f: Filters) => get<ProductRow[]>(`/api/products${toQuery(f)}`),
  customers: (f: Filters, limit = 30) =>
    get<CustomerResponse>(`/api/customers${toQuery(f, { limit })}`),
  statistics: () => get<StatsResponse>('/api/statistics'),
  timeseries: () => get<TimeSeriesResponse>('/api/timeseries'),
  anomalies: () => get<AnomalyResponse>('/api/anomalies'),
  dataQuality: () => get<DataQualityResponse>('/api/data-quality'),
  seasonalComponents: () =>
    get<{ month_start: string; observed: number; stl_trend: number; stl_seasonal: number }[]>(
      '/api/seasonal-components',
    ),
  sqlQueries: () => get<SqlQuery[]>('/api/sql/queries'),
  sqlRun: (name: string) => get<SqlResult>(`/api/sql/run/${name}`),
}
