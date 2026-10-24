// Static display labels for tool steps (D-07). Labels live here, never in the
// backend tool docstrings (those are the model's prompt). Pure module, like
// errors.ts, so it is unit-testable without a browser.

export const TOOL_LABELS: Record<string, string> = {
  spending_total: "Spending total",
  income_total: "Income total",
  net_total: "Net total",
  spending_by_category: "Spending by category",
  spending_in_category: "Spending in category",
  spending_before_after_purchase: "Spending around a purchase",
  transaction_count: "Transaction count",
  largest_transactions: "Largest transactions",
  average_daily_spending: "Average daily spending",
  monthly_trend: "Monthly trend",
  compare_periods: "Compare periods",
  recurring_charges: "Recurring charges",
  account_balances: "Account balances",
  net_worth: "Net worth",
  list_categories: "Category list",
  find_transactions: "Find transactions",
  find_platforms: "Find platforms",
  find_accounts: "Find accounts",
  read_attachment: "Read attached file",
  propose_statement_rows: "Propose file rows",
};

/** snake_case to "Snake case". */
export function humanize(s: string): string {
  const t = s.replace(/_/g, " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? humanize(name);
}

export const ARG_LABELS: Record<string, string> = {
  period: "Period",
  start_date: "From",
  end_date: "To",
  category: "Category",
  kind: "Kind",
  limit: "Limit",
  months: "Months",
  merchant: "Merchant",
  ticker: "Ticker",
  name: "Name",
  period_a: "First period",
  period_b: "Second period",
  window_days: "Window (days)",
};

export const ARG_ORDER = [
  "category",
  "period",
  "start_date",
  "end_date",
  "kind",
  "merchant",
  "ticker",
  "name",
  "limit",
  "months",
];

// A resolved-source chip as sent by the server (sources.source_for).
export type Source = {
  tool?: string;
  label: string;
  period_label: string;
  date_from?: string;
  date_to?: string;
  category?: string;
  account_id?: number;
  type?: string;
  cashflow?: boolean;
  linked: boolean;
};

const PERIOD_KEYS = new Set(["period", "period_a", "period_b"]);

function formatValue(key: string, v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) {
    const parts = v.map((x) => formatValue(key, x)).filter((x): x is string => !!x);
    return parts.length ? parts.join(", ") : null;
  }
  if (typeof v === "object") return null; // never render raw JSON (D-08)
  const s = String(v).trim();
  if (!s) return null;
  if (s === "custom") return "Custom range";
  if (PERIOD_KEYS.has(key) || /^[a-z]+(_[a-z]+)+$/.test(s)) return humanize(s);
  return s;
}

// Local calendar day: new Date(y, m - 1, d) avoids the UTC shift of Date.parse.
function localDay(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function formatDateRange(from?: string, to?: string, locale?: string): string {
  const full = new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", year: "numeric" });
  const short = new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" });
  if (from && to) {
    const a = localDay(from);
    const b = localDay(to);
    const left = a.getFullYear() === b.getFullYear() ? short.format(a) : full.format(a);
    return `${left} – ${full.format(b)}`;
  }
  if (from) return `From ${full.format(localDay(from))}`;
  if (to) return `Until ${full.format(localDay(to))}`;
  return "";
}

export function argRows(
  args: Record<string, unknown>,
  sources: Source[] = [],
): { label: string; value: string }[] {
  const keys = [
    ...ARG_ORDER.filter((k) => k in args),
    ...Object.keys(args).filter((k) => !ARG_ORDER.includes(k)),
  ];
  const rows: { label: string; value: string }[] = [];
  for (const k of keys) {
    const value = formatValue(k, args[k]);
    if (value !== null) rows.push({ label: ARG_LABELS[k] ?? humanize(k), value });
  }
  const dated = sources.filter((s) => s.date_from || s.date_to);
  for (const s of dated) {
    rows.push({
      label: dated.length === 1 ? "Dates" : s.period_label,
      value: formatDateRange(s.date_from, s.date_to),
    });
  }
  return rows.length ? rows : [{ label: "", value: "No filters" }];
}

function minSec(ms: number): string {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/** Whole seconds, for the ticking live line. */
export function formatElapsed(ms: number): string {
  if (ms >= 60_000) return minSec(ms);
  return `${Math.max(0, Math.floor(ms / 1000))}s`;
}

/** Final step duration: one decimal under 10 s, whole seconds up to 59 s. */
export function formatDuration(ms: number): string {
  if (ms >= 60_000) return minSec(ms);
  if (ms < 10_000) return `${(Math.floor(ms / 100) / 10).toFixed(1)}s`;
  return `${Math.floor(ms / 1000)}s`;
}
