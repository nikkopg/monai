"use client";

// ---------------------------------------------------------------------------
// /inbox — the minimal approval Inbox (33-UI-SPEC). Lists pending proposals
// from every channel through the Next proxy, which attaches the approver key
// so MCP codes appear. D-02 replaces the UI-SPEC's list-401 trigger: the
// page-level approver-key alert fires when a live MCP card arrives without a
// code. Cards that settle in-session keep their slot until reload.
// ---------------------------------------------------------------------------

import { useEffect, useMemo, useRef, useState } from "react";
import InboxCard from "./InboxCard";
import { useVisiblePoll } from "../lib/useVisiblePoll";
import {
  APPROVER_KEY_PAGE_MSG,
  hhmm,
  liveCount,
  mergePoll,
  serverOffset,
  type CardPhase,
  type HeldCard,
  type InboxProposal,
  type ProposalRow,
} from "../lib/inbox";
import { btnGhost, card as cardStyle, tokens } from "../styles";

const c = tokens.color;
const OFFLINE_BANNER_ID = "inbox-offline-banner";
const emit = (name: string, detail?: number) =>
  window.dispatchEvent(new CustomEvent(name, { detail }));

export default function InboxPage() {
  const [cards, setCards] = useState<HeldCard[] | null>(null);
  const cardsRef = useRef<HeldCard[] | null>(null);
  const busyRef = useRef<Set<string>>(new Set());
  const offsetRef = useRef(0);
  const lastLive = useRef<number | null>(null);
  const publishedOffline = useRef(false);
  const [tick, setTick] = useState(() => Date.now());
  const [offset, setOffset] = useState(0);
  const [liveMsg, setLiveMsg] = useState("");

  // The single place held cards change, so merges always see the latest state.
  const commit = (next: HeldCard[]) => {
    cardsRef.current = next;
    setCards(next);
  };
  const announce = (msg: string) => setLiveMsg(msg);

  const poll = useVisiblePoll<InboxProposal[]>({
    url: "/api/proposals?status=pending",
    intervalMs: 10_000,
    parse: (json) => (Array.isArray(json) ? (json as InboxProposal[]) : null),
    onData: (list, dateHeader) => {
      const now = Date.now();
      const off = serverOffset(dateHeader, now);
      offsetRef.current = off;
      setOffset(off);
      setTick(now);
      const r = mergePoll(cardsRef.current ?? [], list, busyRef.current, now + off);
      commit(r.cards);
      const n = liveCount(r.cards);
      const first = lastLive.current === null;
      if (r.expired > 0) announce("A proposal expired");
      else if (r.vanished > 0) announce("A proposal was decided elsewhere");
      else if (first && r.cards.length === 0) announce("Inbox is empty");
      else if (!first && n !== lastLive.current) announce(`Inbox updated: ${n} waiting`);
      lastLive.current = n;
    },
  });

  const loaded = cards !== null;

  // Keep the sidebar badge in step with the list, settled cards included.
  useEffect(() => {
    if (cards !== null) emit("monai:inbox-count", liveCount(cards));
  }, [cards]);

  // Tell the Nav when the list goes offline / comes back; hand back on unmount.
  useEffect(() => {
    if (!loaded) return;
    if (poll.offline && !publishedOffline.current) {
      publishedOffline.current = true;
      emit("monai:inbox-offline");
      announce("Can't reach monai. Retrying.");
    } else if (!poll.offline && publishedOffline.current) {
      publishedOffline.current = false;
      emit("monai:inbox-online");
      announce("Back online.");
    }
  }, [poll.offline, loaded]);
  useEffect(
    () => () => {
      if (publishedOffline.current) emit("monai:inbox-online");
    },
    []
  );

  // 30 s ticker: re-render relative times and expire due cards. Paused while hidden.
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const beat = () => {
      const now = Date.now();
      setTick(now);
      const held = cardsRef.current;
      if (!held) return;
      const nowMs = now + offsetRef.current;
      let moved = false;
      const next = held.map((h) => {
        if (h.phase !== "live" || busyRef.current.has(h.proposal.id)) return h;
        if (Date.parse(h.proposal.expires_at) > nowMs) return h;
        moved = true;
        return { ...h, phase: "expired" as CardPhase, settledAt: now };
      });
      if (moved) {
        commit(next);
        announce("A proposal expired");
      }
    };
    const stop = () => {
      if (timer !== null) clearInterval(timer);
      timer = null;
    };
    const start = () => {
      stop();
      timer = setInterval(beat, 30_000);
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") stop();
      else {
        beat();
        start();
      }
    };
    if (document.visibilityState !== "hidden") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  const patch = (id: string, f: (h: HeldCard) => HeldCard) =>
    commit((cardsRef.current ?? []).map((h) => (h.proposal.id === id ? f(h) : h)));
  const onBusy = (id: string, busy: boolean) => {
    if (busy) busyRef.current.add(id);
    else busyRef.current.delete(id);
  };
  const onSettle = (id: string, phase: CardPhase) =>
    patch(id, (h) => ({ ...h, phase, settledAt: Date.now() }));
  const onRows = (id: string, rows: ProposalRow[]) =>
    patch(id, (h) => ({ ...h, proposal: { ...h.proposal, payload: { ...h.proposal.payload, rows } } }));

  const nowMs = tick + offset;
  const pageIds = useMemo(() => new Set((cards ?? []).map((h) => h.proposal.id)), [cards]);
  const needsKey = (cards ?? []).some(
    (h) =>
      h.phase === "live" &&
      h.proposal.channel === "mcp" &&
      !(typeof h.proposal.code === "string" && h.proposal.code !== "")
  );
  const box: React.CSSProperties = { ...cardStyle, padding: "40px 24px", textAlign: "center" };

  let body: React.ReactNode;
  if (cards === null) {
    body =
      poll.failures === 0 ? (
        <div style={box}>
          <p role="status" style={{ fontSize: 14, color: c.muted3, margin: 0 }}>
            Loading your inbox…
          </p>
        </div>
      ) : (
        <div style={box}>
          <p role="alert" style={{ fontSize: 14, color: c.terracotta, margin: "0 0 16px" }}>
            Couldn't load your inbox — check the backend is running and try again.
          </p>
          <button type="button" style={{ ...btnGhost, minHeight: 40 }} onClick={poll.refetchNow}>
            Try again
          </button>
        </div>
      );
  } else if (cards.length === 0) {
    body = (
      <div style={box}>
        <h2 style={{ fontFamily: tokens.font.serif, fontSize: 20, fontWeight: 400, margin: 0 }}>
          All caught up.
        </h2>
        <p style={{ fontSize: 14, color: c.muted3, margin: "8px 0 0" }}>
          Proposals from Claude and chat land here. Nothing is waiting for you.
        </p>
      </div>
    );
  } else {
    body = (
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {cards.map((h) => (
          <li key={h.proposal.id} style={{ marginBottom: tokens.space.lg }}>
            <InboxCard
              card={h}
              nowMs={nowMs}
              offline={poll.offline}
              offlineBannerId={OFFLINE_BANNER_ID}
              onPageIds={pageIds}
              replacementId={
                cards.find((o) => o.proposal.supersedes_id === h.proposal.id)?.proposal.id ?? null
              }
              onBusy={onBusy}
              onSettle={onSettle}
              onRows={onRows}
              announce={announce}
            />
          </li>
        ))}
      </ul>
    );
  }

  return (
    <section className="tab-in" style={{ padding: "40px 44px 60px" }}>
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {liveMsg}
      </div>

      <div style={{ marginBottom: 32 }}>
        <div
          style={{
            fontSize: 12,
            color: c.muted3,
            textTransform: "uppercase",
            letterSpacing: ".12em",
            marginBottom: 8,
          }}
        >
          Approvals
        </div>
        <h1
          style={{
            fontFamily: tokens.font.serif,
            fontWeight: 400,
            fontSize: 40,
            margin: 0,
            letterSpacing: "-.5px",
          }}
        >
          Inbox
        </h1>
        <p style={{ fontSize: 14, color: c.muted3, margin: "8px 0 0" }}>
          Everything waiting for your say-so. Nothing changes until you approve.
          {cards !== null && cards.length > 0 && ` ${liveCount(cards)} waiting.`}
        </p>
      </div>

      {loaded && poll.offline && (
        <div
          id={OFFLINE_BANNER_ID}
          role="status"
          style={{
            background: c.tintWarm,
            border: `1px solid ${c.border2}`,
            borderRadius: tokens.radius.md,
            padding: "12px 16px",
            fontSize: 14,
            color: c.ink,
            marginBottom: 16,
          }}
        >
          Can't reach monai · retrying (last update{" "}
          {poll.lastSuccessAt !== null ? hhmm(poll.lastSuccessAt) : "—"})
        </div>
      )}

      {needsKey && (
        <div
          role="alert"
          style={{
            ...cardStyle,
            padding: "12px 16px",
            marginBottom: 16,
            fontSize: 14,
            color: c.terracotta,
          }}
        >
          {APPROVER_KEY_PAGE_MSG}
        </div>
      )}

      {body}
    </section>
  );
}
