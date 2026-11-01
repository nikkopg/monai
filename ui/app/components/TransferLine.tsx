"use client";

// One transfer sentence plus, for a USD<->IDR pair, the implied-vs-ECB rate line
// (Phase 45, D-04, D-09). Shared by the Inbox card and the chat proposal card.
// Display only: the implied rate is derived from the two typed amounts and is
// never stored or sent with Approve (MOVE-04). The ECB rate comes from the
// cache-only /api/fx/rate; a missing rate reads "ECB rate unavailable", never a guess.
import { fmtRowDate, fmtUnsigned } from "../lib/inbox";
import { useEcbRate } from "../lib/ecb";
import { fmtAmount, fmtRateCompare, impliedRate } from "../lib/money";
import { tokens } from "../styles";

type Leg = Record<string, unknown> | undefined;

const text = (v: unknown): string => (v === null || v === undefined ? "" : String(v));
const abs = (v: unknown): number => Math.abs(Number(v));
// An absent currency is an IDR leg, as before USD accounts existed.
export const legCurrency = (leg: Leg): string => text(leg?.currency) || "IDR";

const jakartaToday = (): string =>
  new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Jakarta" });

export default function TransferLine({
  legA,
  legB,
  showRate,
}: {
  legA: Leg;
  legB: Leg;
  showRate: boolean;
}) {
  const ccyA = legCurrency(legA);
  const ccyB = legCurrency(legB);
  const when = legA?.date ? fmtRowDate(legA.date) : "the approval date";
  const names = `from ${text(legA?.account)} to ${text(legB?.account)}`;

  const usdLeg = ccyA === "USD" ? legA : ccyB === "USD" ? legB : undefined;
  const idrLeg = ccyA === "IDR" ? legA : ccyB === "IDR" ? legB : undefined;
  const mixed = ccyA !== ccyB && !!usdLeg && !!idrLeg;
  const implied = mixed ? impliedRate(abs(idrLeg?.amount), abs(usdLeg?.amount)) : null;
  // The ECB rate of the transfer's day; undated means the day it is approved.
  const ecb = useEcbRate(
    "USD",
    legA?.date ? String(legA.date).slice(0, 10) : jakartaToday(),
    showRate && implied !== null
  );

  let sentence: string;
  if (ccyA !== ccyB) {
    sentence = `Transfer ${fmtAmount(abs(legA?.amount), ccyA)} ${names}, receiving ${fmtAmount(abs(legB?.amount), ccyB)} on ${when}`;
  } else if (ccyA === "USD") {
    sentence = `Transfer ${fmtAmount(abs(legA?.amount), "USD")} ${names} on ${when}`;
  } else {
    sentence = `Transfer ${fmtUnsigned(legA?.amount)} ${names} on ${when}`;
  }

  return (
    <>
      <div style={{ fontSize: 14, color: tokens.color.ink }}>{sentence}</div>
      {showRate && implied !== null && (
        <div aria-live="polite" style={{ marginTop: 4, fontSize: 12, color: tokens.color.muted3 }}>
          {fmtRateCompare(implied, ecb.rate, ecb.rateDate, ecb.status)}
        </div>
      )}
    </>
  );
}
