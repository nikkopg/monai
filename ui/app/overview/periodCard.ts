// Pure helpers for the Cashflow card: which date window the
// Week / Month / Year stepper shows, the same-elapsed-span window it is compared
// against, the change badge and the spent bar. No React; dates are local Date
// objects (never toISOString, which shifts to UTC) and every range is ISO with
// the end INCLUSIVE, the contract of /cashflow/summary?period=custom.
import { fmtAmount } from "../lib/money";

export type PeriodKind = "week" | "month" | "year";

export const PERIOD_KINDS: { value: PeriodKind; label: string }[] = [
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
];

export type PeriodWindow = {
  start: string;
  end: string;
  prevStart: string;
  prevEnd: string;
  title: string;
  short: string; // the chart label under a bar: "Nov", "9 Nov", "2026"
  span: string;
  prevSpan: string;
  inProgress: boolean;
};

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const monthName = new Intl.DateTimeFormat("en-US", { month: "short" });
const daysIn = (y: number, m: number) => new Date(y, m + 1, 0).getDate();

// "1–11 Nov", "9 Nov", "26 Oct–1 Nov". The year is named only when it differs
// from refYear (null: always), and a span across two years names both.
function fmtSpan(s: Date, e: Date, refYear: number | null): string {
  const [sy, ey] = [s.getFullYear(), e.getFullYear()];
  if (sy !== ey) return `${s.getDate()} ${monthName.format(s)} ${sy}–${e.getDate()} ${monthName.format(e)} ${ey}`;
  const year = sy === refYear ? "" : ` ${sy}`;
  if (s.getMonth() !== e.getMonth()) {
    return `${s.getDate()} ${monthName.format(s)}–${e.getDate()} ${monthName.format(e)}${year}`;
  }
  const days = s.getDate() === e.getDate() ? `${s.getDate()}` : `${s.getDate()}–${e.getDate()}`;
  return `${days} ${monthName.format(s)}${year}`;
}

/**
 * The window `offset` periods from the one containing `today` (0 = now, -1 = the
 * one before), and the window it is compared with. In progress (offset 0) the
 * window runs from the period start to today and the comparison covers the same
 * elapsed span of the previous period (same day of month clamped to its length,
 * same weekday, same calendar date a year back); a past period compares whole
 * period with whole period. Weeks start Monday, like the backend's this_week.
 */
export function periodWindow(kind: PeriodKind, offset: number, today: Date): PeriodWindow {
  const [y, m, d] = [today.getFullYear(), today.getMonth(), today.getDate()];
  const now = new Date(y, m, d);
  const inProgress = offset === 0;
  let start: Date, full: Date, prevStart: Date, prevFull: Date, prevElapsed: Date;
  let title: string, short: string;

  if (kind === "month") {
    start = new Date(y, m + offset, 1);
    full = new Date(y, m + offset + 1, 0);
    prevStart = new Date(y, m + offset - 1, 1);
    prevFull = new Date(y, m + offset, 0);
    prevElapsed = new Date(y, m + offset - 1, Math.min(d, prevFull.getDate()));
    title = `${monthName.format(start)} ${start.getFullYear()}`;
    short = monthName.format(start);
  } else if (kind === "week") {
    const sinceMonday = (today.getDay() + 6) % 7;
    const monday = d - sinceMonday + 7 * offset;
    start = new Date(y, m, monday);
    full = new Date(y, m, monday + 6);
    prevStart = new Date(y, m, monday - 7);
    prevFull = new Date(y, m, monday - 1);
    prevElapsed = new Date(y, m, monday - 7 + sinceMonday);
    title = fmtSpan(start, full, null);
    short = `${start.getDate()} ${monthName.format(start)}`;
  } else {
    start = new Date(y + offset, 0, 1);
    full = new Date(y + offset, 11, 31);
    prevStart = new Date(y + offset - 1, 0, 1);
    prevFull = new Date(y + offset - 1, 11, 31);
    prevElapsed = new Date(y + offset - 1, m, Math.min(d, daysIn(y + offset - 1, m)));
    title = String(start.getFullYear());
    short = title;
  }

  const end = inProgress ? now : full;
  const prevEnd = inProgress ? prevElapsed : prevFull;
  const ref = start.getFullYear();
  return {
    start: iso(start),
    end: iso(end),
    prevStart: iso(prevStart),
    prevEnd: iso(prevEnd),
    title,
    short,
    span: fmtSpan(start, end, ref),
    prevSpan: fmtSpan(prevStart, prevEnd, ref),
    inProgress,
  };
}

/**
 * The six windows the Cashflow chart draws for `selected`, each a periodWindow
 * plus its offset. The frame ends at the latest period by default
 * (min(0, selected + 5)), so the highlight can move left and right with the
 * steppers; it slides back only when the selection steps past the oldest bar,
 * leaving the selected bar at the left edge. The in-progress window keeps the
 * figures' start-to-today range.
 */
export function chartWindows(
  kind: PeriodKind,
  selected: number,
  today: Date
): (PeriodWindow & { offset: number })[] {
  const end = Math.min(0, selected + 5);
  return Array.from({ length: 6 }, (_, i) => {
    const offset = end - 5 + i;
    return { offset, ...periodWindow(kind, offset, today) };
  });
}

export type Badge = {
  text: string;
  dir: "up" | "down" | null;
  tone: "good" | "bad" | "flat";
  title: string;
};

/**
 * "+12%" / "−8%" against the previous period, relative to its absolute value.
 * Direction is the arrow; tone says whether that direction is good for this
 * figure (goodWhenUp). Under 0.5% reads a flat "0%"; a zero base reads "new".
 */
export function changeBadge(curr: number, prev: number, goodWhenUp: boolean, vs: string): Badge {
  const was = `vs ${vs} (${fmtAmount(prev)})`;
  if (prev === 0) {
    return curr === 0
      ? { text: "0%", dir: null, tone: "flat", title: `No change ${was}` }
      : { text: "new", dir: null, tone: "flat", title: `New ${was}` };
  }
  const pct = ((curr - prev) / Math.abs(prev)) * 100;
  if (Math.abs(pct) < 0.5) return { text: "0%", dir: null, tone: "flat", title: `No change ${was}` };
  const n = Math.round(Math.abs(pct));
  const up = pct > 0;
  return {
    text: `${up ? "+" : "−"}${n}%`,
    dir: up ? "up" : "down",
    tone: up === goodWhenUp ? "good" : "bad",
    title: `${up ? "Up" : "Down"} ${n}% ${was}`,
  };
}

/**
 * Share of income spent, for the bar under Expenses. Null without income (no
 * bar); "N% over" past 100 so an overspent period never reads "0% kept".
 */
export function spendBar(income: number, expense: number): { spent: number; width: number; kept: string } | null {
  if (income <= 0) return null;
  const spent = Math.round((expense / income) * 100);
  return {
    spent,
    width: Math.min(spent, 100),
    kept: spent > 100 ? `${spent - 100}% over` : `${100 - spent}% kept`,
  };
}

const OTHERS_GREY = "#c8c1b5";

/**
 * The donut slices and legend rows: rows sorted by total, the top n kept and
 * the rest folded into one grey "Others" row, each with its rounded share of
 * the whole. Exactly n+1 rows all stay named: folding a single row would only
 * hide its name.
 */
// ponytail: the backend caps root groups at 10 (_spending_by_category limit), so
// Others covers groups 6-10 only, the same cap the donut already had; raise the
// limit there to widen it.
export function topCategories<T extends { id: number; name: string; color: string | null; icon: string | null; total: number }>(
  rows: T[],
  n = 5
): (T & { share: number })[] {
  const sorted = [...rows].sort((a, b) => b.total - a.total);
  const all = sorted.reduce((sum, r) => sum + r.total, 0);
  const share = (total: number) => (all === 0 ? 0 : Math.round((total / all) * 100));
  const kept = sorted.length > n + 1 ? sorted.slice(0, n) : sorted;
  const rest = sorted.slice(kept.length);
  const shown = kept.map((r) => ({ ...r, share: share(r.total) }));
  if (rest.length === 0) return shown;
  const total = rest.reduce((sum, r) => sum + r.total, 0);
  const others = { id: -1, name: "Others", color: OTHERS_GREY, icon: null, children: [], total, share: share(total) };
  return [...shown, others as unknown as T & { share: number }];
}
