import { expect, test } from "@playwright/test";

import { tokens } from "../app/styles";

// Node-only WCAG 2.x contrast test over the chat token pairs (D-23, UI-SPEC
// "Contrast resolution"). No browser; the helpers are test-only.
function lum(hex: string): number {
  const h = hex.length === 4 ? "#" + hex.slice(1).split("").map((d) => d + d).join("") : hex; // #fff
  const c = [1, 3, 5].map((i) => {
    const v = parseInt(h.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
function ratio(fg: string, bg: string): number {
  const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return (a + 0.05) / (b + 0.05);
}

type Key = keyof typeof tokens.color;
const SIX: Key[] = ["panel", "card", "sidebar", "tintNeutral", "tintWarm", "inputBg"];
const FIVE: Key[] = ["panel", "card", "sidebar", "tintNeutral", "tintWarm"];

// Exactly the UI-SPEC table: 6 + 12 + 5 + 2 + 2, plus ink on tintGreen (Phase 39 Inbox badge).
const PAIRS: [Key, Key][] = [
  ...SIX.map((b): [Key, Key] => ["muted3", b]),
  ...SIX.map((b): [Key, Key] => ["ink", b]),
  ...SIX.map((b): [Key, Key] => ["textSoft", b]),
  ...FIVE.map((b): [Key, Key] => ["terracottaText", b]),
  ["green", "panel"],
  ["green", "card"],
  ["inkText", "ink"],
  ["inkTextMuted", "ink"],
  ["ink", "tintGreen"],
];

test("pair list matches the UI-SPEC table", () => {
  expect(PAIRS).toHaveLength(28);
});

for (const [fg, bg] of PAIRS) {
  test(`${fg} on ${bg} is at least 4.5:1`, () => {
    const c = tokens.color as Record<string, string>;
    expect(ratio(c[fg], c[bg]), `${fg} (${c[fg]}) on ${bg} (${c[bg]})`).toBeGreaterThanOrEqual(4.5);
  });
}

test("control: muted on panel fails, so the detector works", () => {
  expect(ratio(tokens.color.muted, tokens.color.panel)).toBeLessThan(4.5);
});
