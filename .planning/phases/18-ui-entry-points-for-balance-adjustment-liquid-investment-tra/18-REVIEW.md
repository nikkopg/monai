---
phase: 18-ui-entry-points-for-balance-adjustment-liquid-investment-tra
reviewed: 2026-08-17T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - ui/app/cashflow/AccountManager.tsx
  - ui/app/cashflow/AdjustBalanceModal.tsx
  - ui/app/investments/DepositCashModal.tsx
  - ui/app/investments/HoldingModal.tsx
  - ui/app/investments/[platformId]/page.tsx
  - ui/e2e/balance-adjust.spec.ts
  - ui/e2e/funded-trade.spec.ts
  - ui/e2e/investment-transfer.spec.ts
findings:
  critical: 3
  warning: 13
  info: 5
  total: 21
status: issues_found
---

# Phase 18: Code Review Report

**Reviewed:** 2026-08-17
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Three money-moving UI surfaces (ACCT-02 balance adjust, XFER-02 deposit cash, XFER-03 funded
buy/sell) plus three route-mocked Playwright specs. The write contracts line up with the
Phase 13 backend (`target_balance` unsigned/signless, unsigned `amount`/`cash_amount` with
sign applied server-side, `platform_id` numeric, delta recomputed server-side from a fresh
unfiltered SUM), and `account_balances.current_balance` does include transfer rows, so the
delta-preview basis is the right one. Submit guards mostly mirror the Pydantic `gt=0`
constraints and all three modals disable submit while saving.

Verified by running: all 9 new specs **pass** against a fresh `next dev` — but they fail 9/9
via the documented `npm run e2e` on this machine (WR-08), so the phase's own evidence is not
reproducible as-shipped.

Three blocking defects: a stale-response race reintroduced by the `cancelled` → `cancelledRef`
refactor on the platform detail page (renders another platform's PnL / can overwrite a
post-write refetch), a one-day-early event date on the new funded buy/sell writes
(empirically reproduced in WIB), and an unvalidated free-text Currency field that can make a
cash deposit silently vanish from platform subtotal and net worth. The recurring theme in the
warnings is copy-paste drift: `extractDetail`/`fmtPlain` were duplicated rather than shared,
and the copies have diverged in exactly the places that break (error rendering, date
handling, currency handling).

## Critical Issues

### CR-01: `cancelledRef` is shared across `load()` calls — stale-response race renders the wrong platform's money

**File:** `ui/app/investments/[platformId]/page.tsx:124,136-152,171-178`
**Issue:** The refactor from a per-invocation `let cancelled = false` closure (pre-diff) to a
single component-level `cancelledRef` broke the guard. Every `load()` invocation now reads the
*same* mutable flag, and the effect resets it to `false` on each run:

```ts
const cancelledRef = useRef(false);       // shared by ALL load() calls
useEffect(() => {
  cancelledRef.current = false;           // un-cancels any in-flight older load
  load();
  return () => { cancelledRef.current = true; };
}, [platformId]);
```

Two reachable failures:
1. Client-side navigation `/investments/5` → `/investments/7` reuses the same component
   instance (no unmount): cleanup sets `true`, the new effect immediately sets `false`, so
   platform 5's slow response passes the guard and `setDetail(d)` paints platform 5's
   holdings, subtotal and PnL on platform 7's page.
2. `onSaved={load}` fires a second `load()` while the first may still be in flight — no
   ordering guarantee, so a stale pre-write response can land last and show the user's
   deposit/trade as not applied.

**Fix:** Use a per-invocation token instead of one shared boolean:

```ts
const loadSeq = useRef(0);

async function load() {
  const seq = ++loadSeq.current;
  const isStale = () => seq !== loadSeq.current;
  ...
  if (!isStale()) { setDetail(d); setEvents(e); }
  ...
}

useEffect(() => {
  load();
  return () => { loadSeq.current++; };   // invalidate in-flight loads
}, [platformId]);
```

(Restoring the original per-call `let cancelled` and passing it into a helper is equally
valid — the invariant is one flag per request, never one per component.)

### CR-02: funded buy/sell records the event one day early (local times before 07:00 WIB)

**File:** `ui/app/investments/HoldingModal.tsx:141` (new; same expression pre-exists at `:171`)
**Issue:** `date` is a `datetime-local` wall-clock string, but the payload does:

```ts
date: new Date(date).toISOString().slice(0, 10),
```

`new Date("2026-08-17T02:30")` parses as *local*; `toISOString()` converts to UTC, so in WIB
(UTC+7) any wall-clock time between 00:00 and 06:59 slices to the **previous** calendar day.
Verified on this machine (`TZ=Asia/Jakarta`):

```
input local 2026-08-17T02:30 -> 2026-08-16
```

The default `date` value is `new Date()`, so a trade logged in the early morning silently
books a day early — on both legs (cash `Transaction.date` and `PortfolioEvent.date`). That
mis-buckets the cash leg in cashflow/monthly trend, mis-keys the date-scoped FX/price lookups
in `recompute_holding_from_events`, and can reorder cost-basis/realized-PnL computation.
The file already carries the countermeasure and a comment naming this exact hazard
(`toLocalDatetimeInputValue` … "avoids the toISOString() UTC shift") — the submit path just
doesn't use its inverse. `DepositCashModal` gets this right by passing the `<input type="date">`
value straight through.

**Fix:** Add the inverse local-date helper and use it on **both** submit paths (root cause:
one shared helper, not a patch on the new line only):

```ts
// local calendar date of a datetime-local value — never toISOString()
const toLocalDateOnly = (v: string) => v.slice(0, 10);
// (the datetime-local value is already local YYYY-MM-DDTHH:mm)
...
date: toLocalDateOnly(date),
```

### CR-03: unvalidated free-text Currency on the deposit write can make the money disappear from net worth

**File:** `ui/app/investments/DepositCashModal.tsx:61,204-209,107`
**Issue:** Currency is a free-text `<input>` (`value={currency}`, no `pattern`, no
normalization) whose value is posted verbatim as `currency: currency || "IDR"`. The backend
copies it into `Transaction.currency` **and** the `deposit` `PortfolioEvent` → the CASH
sentinel `Holding.currency`. `portfolio_summary` values cash as
`quantity × fx.get_rate(h.currency, "IDR", today)`, and `fx.get_rate` returns `None` for
anything failing `^[A-Z]{3,4}$` (`backend/fx.py:104`). So a single typo — `Rp`, `IDRR`,
`Rupiah` — produces a holding with `current_value = None`: the deposit is dropped from the
platform subtotal and from net worth, badged stale, with no error anywhere. The cash leg still
debits the liquid account, so money is destroyed from the user's point of view. The sibling
surface (`HoldingModal`) hardcodes `"IDR"`, so this field is also the only inconsistent
currency entry point in the phase.

**Fix:** Don't take free text for a money-classifying field. Simplest correct version
matching the project's single-currency (IDR) constraint:

```tsx
<select id="deposit-cash-currency" style={input} value={currency}
        onChange={(e) => setCurrency(e.target.value)}>
  <option value="IDR">IDR</option>
</select>
```

If multi-currency entry is actually wanted, source the options from the fetched
`Account.currency` values (already available and currently discarded — see WR-10) and
validate `^[A-Z]{3,4}$` client-side before enabling submit.

## Warnings

### WR-01: a selected Funding account is silently dropped for Dividend

**File:** `ui/app/investments/HoldingModal.tsx:85,117-120,325-338`
**Issue:** `isFunded = fundingAccount !== "" && !isDividend`. Choose "BCA", then switch Event
type to Dividend: the select still visibly reads "BCA", the button reverts to "Log event",
the Cash amount field and the Debits/Credits preview vanish, and the submit writes an
*unfunded* event with no cash leg. The user's explicit funding instruction is discarded with
no notice on a money form.
**Fix:** Make the drop explicit — when `isDividend`, either reset (`setFundingAccount("")` in
`onEventTypeChange`) or `disabled` the select with one line of copy
("Dividends aren't funded from an account").

### WR-02: HoldingModal renders FastAPI 422 validation errors as `[object Object]`

**File:** `ui/app/investments/HoldingModal.tsx:153-160,184-191`
**Issue:** `detail = errBody?.detail ?? detail` assumes `detail` is a string. Pydantic
validation failures return `detail` as an **array of objects**, which the template string
renders as `Couldn't log funded buy: [object Object]. Nothing was changed.` This is reachable
without exotic input: quantity/price inputs have no `min` and the submit guard only checks
`cashAmount > 0`, so `quantity = 0` (or `-1` typed into the funded path) posts and trips the
backend's `gt=0` constraints. The other three files' `extractDetail` at least degrades to
`HTTP 422`.
**Fix:** Reuse the shared `extractDetail` (see WR-12) and add `min="0"`/`step="any"` plus
submit-guard parity with the backend: `!(parseFloat(quantity) > 0) || !(parseFloat(price) > 0)`.

### WR-03: preview and payload parse the target differently; sub-unit deltas display as "+Rp 0"

**File:** `ui/app/cashflow/AdjustBalanceModal.tsx:48,52,59,124-128`
**Issue:** The preview uses `parseFloat(target || "0")` while the body uses
`parseFloat(target)`. Clear the field and the preview asserts a full balance wipe
(`Adjustment: −Rp 1,000,000`) with the submit button **enabled** — only the native `required`
attribute prevents posting `{"target_balance": null}` (NaN → JSON null → 422). Any future
programmatic submit or a change in guard order turns this into a real bad request.
Separately, `fmtPlain` rounds, so a target of `1000000.4` against `1000000` previews
`Adjustment: +Rp 0` while writing a real 0.4 adjustment.
**Fix:** Parse once and gate on validity:

```ts
const parsed = target.trim() === "" ? NaN : parseFloat(target);
const delta = Number.isNaN(parsed) ? 0 : parsed - account.current_balance;
// disabled={saving || Number.isNaN(parsed) || delta === 0}
```

### WR-04: "Adjust balance" is offered for investment-type accounts, where the reconciliation doesn't propagate

**File:** `ui/app/cashflow/AccountManager.tsx:23,209-215`
**Issue:** `GET /cashflow/summary` returns `account_balances()` rows **unfiltered**
(`backend/main.py:856`), i.e. investment-type accounts included, and the UI's
`AccountBalance` type (`ui/app/cashflow/page.tsx:28-33`) drops the backend's `type` field, so
`AccountManager` cannot filter. Adjusting an investment-type account writes a cashflow
`Adjustment` row that `net_worth()` never sees (its liquid side filters `type == 'liquid'`) —
the account list changes, net worth doesn't, with no explanation.
**Fix:** Add `type: string` to the `AccountBalance`/`Account` types and render the trigger
only for `a.type === "liquid"` (matching how `DepositCashModal` and `HoldingModal` already
gate their account pickers).

### WR-05: the backdrop can dismiss a modal mid-write, silently discarding the error path

**File:** `ui/app/cashflow/AdjustBalanceModal.tsx:90`, `ui/app/investments/DepositCashModal.tsx:145`, `ui/app/investments/HoldingModal.tsx:215`
**Issue:** `onClick={onClose}` on the overlay stays live while `saving` is true. Clicking the
backdrop during an in-flight POST unmounts the modal; the `setError(...)` in the failure
branch then lands on an unmounted component and the user is never told the write failed — on
a surface whose whole safety story is "Nothing was changed." copy.
**Fix:** `onClick={saving ? undefined : onClose}` on the overlay (and the same guard on the
Cancel button), in all three modals.

### WR-06: a failed `/api/platforms` fetch disables event logging on a page that already knows its platform

**File:** `ui/app/investments/[platformId]/page.tsx:158-168,565-572`
**Issue:** `platformOptions` is populated by a best-effort secondary fetch. If it fails (or
returns `[]`), `HoldingModal` receives `platforms={[]}` → renders "Add a platform first" and
a permanently disabled submit, even though `detail.platform_name`/`platformId` are already in
hand. The controlled `<select value={platformId}>` also has no matching `<option>`, so it
renders blank.
**Fix:** Fall back to the known platform:

```tsx
platforms={platformOptions.length > 0
  ? platformOptions
  : [{ id: Number(platformId), name: detail.platform_name }]}
```

### WR-07: post-write refetch blanks the whole page and unmounts the modal mid-flight

**File:** `ui/app/investments/[platformId]/page.tsx:126-129,205-210,557-572`
**Issue:** `onSaved={load}` starts with `setLoading(true)`, and both modals are rendered
inside the `!loading` branch — so a successful save replaces the entire page with
"Loading platform…", unmounting the modal before its `finally { setSaving(false) }` runs, then
repaints. Cosmetically a full-page flash on every write; functionally it means any post-write
state in the modal (e.g. a failure surfaced after `onSaved`) is unreachable.
**Fix:** Refetch without the full-page loading state (keep `loading` for the initial mount
only, e.g. `load({ silent: true })` from `onSaved`), or render the modals outside the
`loading` ternary.

### WR-08: `npm run e2e` fails 9/9 — the specs run against a stale pre-Phase-18 build

**File:** `ui/e2e/balance-adjust.spec.ts`, `ui/e2e/investment-transfer.spec.ts`, `ui/e2e/funded-trade.spec.ts` (root cause in `ui/playwright.config.ts:9-11,27-37`)
**Issue:** Two compounding problems make the phase's own evidence non-reproducible:
1. `launchOptions.executablePath` is unconditionally set to the fallback
   `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`, which does not exist here
   (`~/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome` does) →
   `browserType.launch: Failed to launch chromium`.
2. `webServer.reuseExistingServer: true` with `url: http://127.0.0.1:3001` silently reuses the
   `monai-frontend` **Docker container** (image built 2026-08-02, pre-Phase-18) that occupies
   :3001. The captured page snapshot from the failing run shows the platform header **without**
   the "Deposit cash" button — i.e. the old layout. This is the known
   "deploy requires rebuild" trap, now hiding behind a green-looking harness.

Verified: with a fresh `next dev` on :3002 and a real chromium path, **all 9 new specs pass
(27.5s)**. So the specs themselves are sound; the harness is what's broken.
**Fix:** Make the executable path conditional on existence (or drop it and rely on the
default resolver), and stop reusing a foreign server — e.g. `reuseExistingServer: !process.env.CI`
plus a distinct e2e port (`next dev -p 3099`) so a running container can't shadow the build
under test.

### WR-09: name-keyed account resolution can write money to a phantom account

**File:** `ui/app/investments/DepositCashModal.tsx:104`, `ui/app/investments/HoldingModal.tsx:133`, `ui/app/cashflow/AdjustBalanceModal.tsx:56`
**Issue:** `from_account` / `source_account_name` are **names**, resolved server-side by
`_get_or_create_account`. Sourcing them from a `<select>` narrows but does not close
RESEARCH Pitfall 2: the accounts are fetched at modal mount, so a rename or delete between
mount and submit silently *creates a new account* with the stale name and posts the debit
there (a fresh negative-balance account appears in Cashflow). The adjust path is worse — with
a deleted `account.id`, `apply_add_balance_adjustment` (`backend/writes.py:79-107`) computes a
delta against an empty SUM and falls back to `account.name → "Unknown"`, so the adjustment is
written to an account literally named "Unknown".
**Fix:** Send `account_id` (`{id, name}` is already in hand — use `value={a.id}` and look up
the name only for display copy) and have the backend resolve by id; failing that, have the
endpoints reject an unknown account name instead of creating one. The `db.get(Account, id) is
None → ValueError` guard is the same fix pattern already applied in T-14-07.

### WR-10: funded writes hardcode IDR while the funding account's own currency is fetched and discarded

**File:** `ui/app/investments/HoldingModal.tsx:30-35,84,139-140`
**Issue:** `Account.currency` is declared, fetched and never read; the payload always sends
`cash_currency: "IDR"` / `event_currency: "IDR"`. The backend explicitly supports independent
per-leg currencies (D-09, `apply_add_funded_buy` sets `Transaction.currency` and
`PortfolioEvent.currency` from separate inputs), so funding a buy from a non-IDR liquid
account silently mislabels the cash leg's currency — and mislabelled currency is what CR-03
shows can zero out a valuation.
**Fix:** Derive from the selected account:
`cash_currency: liquidAccounts.find(a => a.name === fundingAccount)?.currency ?? "IDR"`, or
delete the unused `currency` field from the local `Account` type and document the IDR-only
assumption in one comment.

### WR-11: the new money trigger is not keyboard-operable

**File:** `ui/app/cashflow/AccountManager.tsx:209-215`
**Issue:** `<span role="button" onClick=...>` with no `tabIndex={0}` and no `onKeyDown` — it
claims the button role to assistive tech but cannot be focused or activated by keyboard.
(Consistent with the pre-existing Edit/Delete spans, so this is convention drift rather than
a one-off, but this is the entry point to a balance-rewriting flow.) None of the three new
modals sets `role="dialog"`/`aria-modal`, traps focus, or closes on `Escape`.
**Fix:** `<button type="button">` with the same inline styles is the smallest correct change
(no new deps, kills the role/tabIndex/keydown triplet at once); add `role="dialog"
aria-modal="true"` plus an `Escape` handler on the new modal shells.

### WR-12: `extractDetail` copy-pasted four times and already diverged; `fmtPlain` five times

**File:** `ui/app/cashflow/AccountManager.tsx:314-326`, `ui/app/cashflow/AdjustBalanceModal.tsx:27-39`, `ui/app/investments/DepositCashModal.tsx:37-49`, `ui/app/investments/HoldingModal.tsx:153-159,184-190`
**Issue:** Three byte-identical copies of `extractDetail` plus two divergent inline variants
in `HoldingModal` — and the divergence is precisely the bug in WR-02. `fmtPlain` is duplicated
across all four components and both new specs. This is not a style nit: the duplication is
what let the error-rendering and date handling drift between the funded and unfunded paths in
the same file.
**Fix:** One `ui/app/lib/api.ts` (or extend `ui/app/styles.ts`'s role as the shared module)
exporting `extractDetail` and `fmtPlain`; import in all four components.

### WR-13: the funded-trade spec has no error path and asserts none of the fields that are wrong

**File:** `ui/e2e/funded-trade.spec.ts:143-275`
**Issue:** Tests A–D assert `source_account_name/platform_id/ticker/quantity/price/cash_amount`
via `toMatchObject` and never assert `date`, `cash_currency`, `event_currency`, or
`asset_type` — which is exactly why CR-02 (day-early date) ships green. There is also no 422
test (both sibling specs have one, so this is an intra-phase inconsistency, not a missing
convention) and no Dividend-with-funding-selected case (WR-01).
**Fix:** Add `date: <expected local YYYY-MM-DD>` (freeze the clock with
`page.clock.install({ time: ... })` at a 02:00 local time to lock the regression),
`cash_currency: "IDR"`, `asset_type: "crypto"` to Test A's `toMatchObject`; add a funded-buy
422 test mirroring `investment-transfer.spec.ts:130`; add a Dividend case asserting the
unfunded endpoint is used.

## Info

### IN-01: unused `fmtPlain` in both new specs

**File:** `ui/e2e/funded-trade.spec.ts:19`, `ui/e2e/investment-transfer.spec.ts:14`
**Issue:** Declared and never referenced (the tests assert literal strings). Dead code that
would fail `noUnusedLocals`.
**Fix:** Delete both, or use them in the expected-copy assertions.

### IN-02: stale "RED spec / does not exist yet" headers

**File:** `ui/e2e/funded-trade.spec.ts:4-11`, `ui/e2e/investment-transfer.spec.ts:4-11`
**Issue:** Both headers still claim "RED now: … does not exist yet" after the implementation
landed and passes. Misleading for the next reader.
**Fix:** Drop the RED/GREEN framing, keep the mocking-convention notes.

### IN-03: duplicate route registration

**File:** `ui/e2e/investment-transfer.spec.ts:72,77-84`
**Issue:** `mockPlatformDetail(page)` registers `**/api/platforms/*/detail`, then the test
registers the same pattern again with the counter. Playwright prefers the later handler, so
the first registration is dead.
**Fix:** Drop the `mockPlatformDetail(page)` call in that test (or give the helper an optional
`onFetch` callback like `mockDashboard` in `balance-adjust.spec.ts`).

### IN-04: inconsistent captured-body typing

**File:** `ui/e2e/funded-trade.spec.ts:152,167,185,201,210,226`
**Issue:** Tests A/C pass the narrowed-to-`null` `captured` straight into `expect(...)`, while
Test B needs `(captured as unknown as Record<string, unknown>)` for the same variable — a
double cast papering over the CFA narrowing rather than fixing it.
**Fix:** Capture into an array (`const posted: Record<string, unknown>[] = []`) and assert on
`posted[0]`; no casts, and it also proves exactly one POST fired.

### IN-05: no NaN guard on the route param

**File:** `ui/app/investments/[platformId]/page.tsx:113,559,568`
**Issue:** `Number(platformId)` / `parseInt(platformId, 10)` on a raw route segment yields
`NaN` for a non-numeric URL, which `JSON.stringify` turns into `null` in the payload. In
practice the `/detail` fetch 404s first and the `notFound` branch renders, so the modals are
unreachable — but the coercion is unguarded.
**Fix:** Parse once at the top and render `notFound` immediately when
`!Number.isInteger(id)`.

---

_Reviewed: 2026-08-17_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
