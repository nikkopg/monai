---
phase: 18
slug: ui-entry-points-for-balance-adjustment-liquid-investment-tra
status: draft
shadcn_initialized: false
preset: none
created: 2026-08-03
---

# Phase 18 — UI Design Contract

> Visual and interaction contract for 3 new entry points on an EXISTING, locked
> design system (v1.1 "paper" aesthetic, `ui/app/styles.ts` inline-style tokens).
> This is NOT a new design system — it is a strict extension. Every value below
> is either quoted from `ui/app/styles.ts` / existing modal code, or a
> prescriptive default filled in for the 3 net-new surfaces (balance-adjust
> dialog, deposit-cash modal, HoldingModal funding selector).

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none — no shadcn, no Tailwind (confirmed: no `components.json`, no `tailwind.config.*` in `ui/`) |
| Preset | not applicable |
| Component library | none — hand-rolled inline `React.CSSProperties`, per `CLAUDE.md` convention |
| Icon library | none — text glyphs only (`←`, `+`), matches existing `investments/page.tsx` ("+ Log event") and platform-detail ("← Investments") |
| Font | `tokens.font.serif` = Instrument Serif (page/display headings only — NOT used in these 3 modals); `tokens.font.sans` = Hanken Grotesk (all modal/body/label/button text — the only font family this phase touches) |

**Source of truth:** `ui/app/styles.ts` (read in full this session). Do not add new tokens, new colors, or a new spacing scale — every value below already exists in that file or in the modal code it's extended from (`HoldingModal.tsx`, `AccountManager.tsx`, `ConfirmDialog.tsx`, `investments/[platformId]/page.tsx`).

---

## Spacing Scale

**This project's locked scale is NOT the GSD default 4pt grid** — it is `tokens.space` from `styles.ts`. Reuse these values verbatim; do not introduce new spacing constants.

| Token | Value | Usage in this phase |
|-------|-------|----------------------|
| `tokens.space.xs` | 6px | Row action gap (Edit / Adjust balance / Delete separators), badge internal padding |
| `tokens.space.sm` | 8px | Button-row gaps (Cancel + Submit), form-row gaps |
| `tokens.space.md` | 14px | Grid-gap between form fields (2-column field grids) |
| `tokens.space.lg` | 18px | Card padding bottom, section gaps (mirrors `card.marginBottom`) |
| `tokens.space.xl` | 24px | Modal outer padding is 32px (see below) — `xl` used for header-to-form gaps |

**Exceptions (already established, reuse verbatim, do not "fix" to the scale above):**
- Modal card padding: `32px` (`HoldingModal.tsx` line 116: `{ ...card, maxWidth: 480, width: "100%", padding: 32, margin: 0 }`) — the balance-adjust dialog and the deposit-cash modal MUST use this exact `padding: 32` override, not `card`'s default `22px 24px`.
- `ConfirmDialog`'s smaller variant uses `padding: 24, maxWidth: 360` — NOT used by this phase's 3 surfaces (none of them are `ConfirmDialog`-hosted; D-07 explicitly rejects a second confirm step).
- Form field grid gap: `10px` (not `tokens.space.md`'s 14px) — `HoldingModal.tsx` line 128 uses `gap: 10` for its 2-column field grid. Reuse `10px` for any new 2-column field grid added to the balance-adjust dialog / deposit-cash modal to stay visually identical to `HoldingModal`.

---

## Typography

All sizes/weights below are the exact values already used by the modals/pages this phase extends — no new sizes introduced.

| Role | Size | Weight | Line Height | Usage |
|------|------|--------|-------------|-------|
| Modal heading | 20px | 600 | 1.2 (default block) | `<h2>` at top of balance-adjust dialog / deposit-cash modal — matches `HoldingModal.tsx` line 119 (`fontSize: 20, fontWeight: 600`) |
| Body / input / button | 14px | 400 (input text), 600 (`btn` label) | 1.5 | Field values, form `<input>`/`<select>` text (`input` token: `fontSize: 14`), primary submit button label (`btn` token: `fontSize: 14, fontWeight: 600`) |
| Label | 12px | 400 | 1.4 | Field labels (`label` token: `fontSize: 12, color: tokens.color.muted2`) |
| Preview / secondary text | 12-13px | 400, or 600 for the money figure itself | 1.4 | Money-impact preview line (all 3 surfaces) — 13px body, the numeric amount rendered `fontWeight: 600` inline within the sentence to draw the eye, matching `statValue`'s weight convention without adopting its 28px size |

**Do not introduce:** any font size not in this table, any font-weight other than 400/600, the serif display font (reserved for page-level `<h1>` titles, not modals).

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) | `tokens.color.card` = `#fff` | Modal card background (`card` token) |
| Secondary (30%) | `tokens.color.inputBg` = `#faf8f4`, `tokens.color.sidebar` = `#f2efe8` | Form field backgrounds (`input` token), disabled/empty-state banners |
| Accent (10%) | `tokens.color.green` = `#2f6f4f` | **Reserved for:** primary submit button background (`btn`), positive money-impact preview values (balance-adjust delta ≥ 0, funded-buy side label) |
| Destructive | `tokens.color.terracotta` = `#b5503f` | **Reserved for:** error copy text, negative/debit money-impact preview values (balance-adjust delta < 0), empty-liquid-accounts warning text, funded-sell side label |

Accent reserved for: the 3 primary submit buttons ("Save adjustment", "Deposit cash", HoldingModal's existing submit), and ONLY the numeric sign-colored portion of a money-preview line when the impact is a net-positive/credit/buy. Never use green as a generic decorative color on labels, borders, or non-monetary UI in this phase.

Destructive reserved for: 422/network error text (existing convention, unchanged), a negative/debit-signed preview figure, and the "no liquid accounts" empty-state warning (mirrors `HoldingModal.tsx` line 170's existing "Add a platform first" pattern, same color/size).

Neutral preview text (transfers that are neither a gain nor a loss, e.g. the deposit-cash "Moves Rp X from A into B" line) uses `tokens.color.text` = `#23201b` (plain ink), not green or terracotta — a liquid→investment transfer isn't itself a gain/loss event.

---

## Copywriting Contract

### Surface 1 — Balance adjustment (ACCT-02), hosted in `AccountManager.tsx`

| Element | Copy |
|---------|------|
| Row trigger (inline text action, next to Edit/Delete) | `Adjust balance` — 12px, `color: tokens.color.muted3` (NOT terracotta; non-destructive), `cursor: pointer`, same visual weight as the existing `Edit` action |
| Modal heading | `Adjust balance — {account name}` |
| Field label | `Target balance` (single number input, `step="any"`, no `min`/`gt=0` — accepts zero/negative per `BalanceAdjustmentCreate`) |
| Live preview (delta ≥ 0) | `Adjustment: +Rp {fmtPlain(delta)}` — green |
| Live preview (delta < 0) | `Adjustment: −Rp {fmtPlain(Math.abs(delta))}` — terracotta |
| Live preview (delta = 0) | `No change — target equals current balance.` — muted (`tokens.color.muted`), submit disabled |
| Primary CTA | `Save adjustment` |
| Cancel | `Cancel` (existing transparent/muted button pattern, unchanged) |
| Error state | `Couldn't save adjustment: {detail}. Nothing was changed.` |
| Empty state | not applicable — this dialog is always opened for one existing account row; no empty state |

### Surface 2 — Deposit cash (XFER-02), hosted in `investments/[platformId]/page.tsx`

| Element | Copy |
|---------|------|
| Header trigger (page action, top of platform detail, `btn` style — primary green) | `Deposit cash` |
| Modal heading | `Deposit cash — {platform name}` |
| Field labels | `From account` (select, liquid accounts only), `Amount`, `Currency` (text, default `IDR`), `Date` (optional, plain `<input type="date">`), `Notes` (optional, text) |
| Live preview | `Moves Rp {fmtPlain(amount)} from {account name} into {platform name}.` — neutral ink color (not green/terracotta) |
| Primary CTA | `Deposit cash` |
| Cancel | `Cancel` |
| Error state | `Couldn't deposit cash: {detail}. Nothing was changed.` |
| Empty state (no liquid accounts) | `No liquid accounts yet — add one in Cashflow before depositing cash.` — terracotta, 11px, mirrors `HoldingModal.tsx`'s "Add a platform first" pattern verbatim; submit disabled while true |

### Surface 3 — Funded buy/sell (XFER-03), extending `HoldingModal.tsx`

| Element | Copy |
|---------|------|
| Buy & Sell tab trigger (new, top of that tab's content on platform detail) | `+ Log event` — reuses `btnDark` style verbatim, matching `investments/page.tsx` line 487-488's existing trigger exactly (same label, same style token) |
| New field label | `Funding account` (select; first option `— none (unfunded) —` value `""`, then liquid accounts from `GET /accounts` filtered `type === "liquid"`) |
| New field label (funded mode only, i.e. a funding account is chosen) | `Cash amount (IDR)` — number input, defaults to `quantity × price`, remains independently editable (D-06); re-syncs to `quantity × price` only when quantity or price changes again, never silently overwrites a manual edit mid-session otherwise |
| Modal heading | unchanged: `Log event` (no funded/unfunded heading variant — keeps the field-set principle from `HoldingModal.tsx`'s dividend handling) |
| Live preview (funded + Buy) | `Debits {account name} Rp {fmtPlain(cash_amount)}, +{quantity} {ticker}` — green (reuses the existing `sideColor()` buy=green convention from `investments/[platformId]/page.tsx`) |
| Live preview (funded + Sell) | `Credits {account name} Rp {fmtPlain(cash_amount)}, −{quantity} {ticker}` — terracotta (reuses `sideColor()` sell=terracotta) |
| Live preview (unfunded, any event type) | none — unchanged from current `HoldingModal.tsx` behavior (no preview line today; not required by D-07, which scopes the preview requirement to money-moving writes, and unfunded logging doesn't move money) |
| Primary CTA (funded) | `Log funded Buy` / `Log funded Sell` (Title-cased event type) |
| Primary CTA (unfunded, unchanged) | `Log event` |
| Error state (funded) | `Couldn't log funded {buy/sell}: {detail}. Nothing was changed.` |
| Error state (unfunded, unchanged) | `Couldn't log event: {detail}. Nothing was changed.` |
| Empty state (no liquid accounts) | Funding-account select still renders with only `— none (unfunded) —` available; no separate warning banner needed — the unfunded escape hatch (D-05) means this is never a blocking empty state, unlike Surface 2 |

### Destructive confirmation

**None in this phase.** All 3 surfaces are additive/money-moving, not deletions. Per D-07, write-safety is a form-level preview line + single atomic submit — explicitly NOT a second `ConfirmDialog` step. Do not add a `ConfirmDialog` wrapper to any of these 3 flows.

---

## Interaction & Field Contracts (supplementary — beyond the standard template, required for this phase's money-safety rules)

### Hard rule: every account field is a `<select>`, never free text

All 3 surfaces populate account pickers exclusively from a freshly-fetched `GET /accounts` response, client-filtered to `type === "liquid"`. This is a correctness requirement, not a style preference — `_get_or_create_account` silently creates a new account on any non-matching free-text name (RESEARCH.md Pitfall 2). No `<input type="text">` may ever back an account-selection field on these 3 surfaces.

### Date field types (per-endpoint, do not conflate)

| Surface | Backend field | Input type | Submit transform |
|---------|---------------|------------|-------------------|
| Balance adjustment | none (`BalanceAdjustmentCreate` has no date field) | n/a | n/a |
| Deposit cash | `date: str \| None` | `<input type="date">` (plain date, not datetime-local) | value is already `YYYY-MM-DD` — send as-is, no `.toISOString()` truncation needed |
| Funded buy/sell (extends existing `date` field) | `date: str \| None` on the funded path vs `date: date` on the existing unfunded `PortfolioEventCreate` path | keep `HoldingModal.tsx`'s existing `datetime-local` input unchanged | keep the existing `.toISOString().slice(0, 10)` truncation for BOTH funded and unfunded submit — do not add a second date-input variant |

### Money formatting

Reuse `fmtPlain`/`fmtSigned`-style `Intl.NumberFormat("en-US")` grouping (as already defined locally in `investments/[platformId]/page.tsx` and `investments/page.tsx`) prefixed with a literal `Rp `. Do not introduce a currency-symbol library or `Intl.NumberFormat({style:'currency'})` (would inject `IDR`/locale symbols inconsistent with the existing `Rp {fmtPlain(...)}` convention already fixed by D-01/D-03/D-07's copy). Signed deltas use an explicit `+`/`−` prefix (`−` is U+2212 minus sign, matching `fmtSigned`'s `signDisplay: "always"` output style already used elsewhere) — do not use a hyphen-minus.

### Numeric input coercion

`parseFloat(...)` on submit for every numeric field (amount, cash_amount, quantity, price, target_balance) — matches `HoldingModal.tsx`'s existing convention (RESEARCH.md Pitfall 4). Never send a numeric field as a string.

### Trigger placement summary

| Trigger | Location | Style |
|---------|----------|-------|
| "Adjust balance" | `AccountManager.tsx` row, inline text action after "Edit", before "Delete" | 12px text link, `color: tokens.color.muted3`, `cursor: pointer` — same visual class as "Edit" (non-destructive) |
| "Deposit cash" | `investments/[platformId]/page.tsx`, page-header area near the `<h1>` platform name (top of page, above the stat-card grid) | `btn` (primary green, 14px/600) |
| "+ Log event" (funded/unfunded entry) | `investments/[platformId]/page.tsx`, top of the "Buy & Sell" tab content (above the event table) — a SECOND trigger site for the same `HoldingModal`, alongside the existing `investments/page.tsx` trigger which is unchanged | `btnDark` (pill, ink background, 13px) — identical to the existing `investments/page.tsx` "+ Log event" button |

When opened from the platform-detail "Buy & Sell" tab trigger, `HoldingModal` receives an optional `defaultPlatformId` prop and pre-selects (not locks/disables) that platform in the Platform `<select>` — the field remains editable, matching the "implied by selection, not a hard toggle" philosophy already used for the funded/unfunded selector.

### Loading / disabled states (reuse existing convention, no new pattern)

- Submit buttons disable while `saving` is true and show `"Saving…"` — exact string already used by `HoldingModal.tsx` line 242; reuse verbatim for all 3 surfaces' primary submit label during the in-flight request.
- Submit is also disabled when: balance-adjust delta === 0; deposit-cash has zero liquid accounts; funded buy/sell has zero liquid accounts is NOT a disable condition (unfunded escape hatch stays available).

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|--------------|
| n/a — no shadcn, no component registry | none | not applicable |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
