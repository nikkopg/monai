import type { Locator } from "@playwright/test";

// Type-scale helpers shared by phone-375.spec.ts and cashflow-dashboard.spec.ts
// (261116-s7w). Not a spec, so Playwright does not run it. Each function runs
// in the page and returns plain data.

export type TextSize = { text: string; px: string; decorative: boolean };

// Every element under root that paints text: a non-zero box, not inside
// .sr-only, and one of: a direct non-blank text-node child, a .roll
// (RollingNumber, whose digits are pseudo-content), an SVG <text>, or a
// rendered input/select/textarea that is not a checkbox, radio or hidden.
export function textSizes(root: Locator): Promise<TextSize[]> {
  return root.evaluate((rootEl) => {
    const out: { text: string; px: string; decorative: boolean }[] = [];
    const formControl = /^(input|select|textarea)$/i;
    for (const el of Array.from(rootEl.querySelectorAll("*"))) {
      if (el.closest(".sr-only")) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const direct = Array.from(el.childNodes).some((n) => n.nodeType === Node.TEXT_NODE && (n.textContent ?? "").trim() !== "");
      const isRoll = el.classList.contains("roll");
      const isSvgText = el.namespaceURI === "http://www.w3.org/2000/svg" && el.tagName.toLowerCase() === "text";
      const type = (el.getAttribute("type") ?? "").toLowerCase();
      const isControl = formControl.test(el.tagName) && !["checkbox", "radio", "hidden"].includes(type);
      if (!direct && !isRoll && !isSvgText && !isControl) continue;
      const own = Array.from(el.childNodes)
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .map((n) => (n.textContent ?? "").trim())
        .join(" ")
        .trim();
      out.push({
        text: (own || el.getAttribute("placeholder") || el.getAttribute("aria-label") || el.tagName.toLowerCase()).slice(0, 30),
        px: getComputedStyle(el).fontSize,
        decorative: el.closest('[aria-hidden="true"]') !== null,
      });
    }
    return out;
  });
}

// Count of entries per computed font size, decorative ones included, with keys
// sorted numerically so a failing diff reads top to bottom.
export async function sizeHistogram(root: Locator): Promise<Record<string, number>> {
  const counts: Record<string, number> = {};
  for (const { px } of await textSizes(root)) counts[px] = (counts[px] ?? 0) + 1;
  return Object.fromEntries(Object.entries(counts).sort((a, b) => parseFloat(a[0]) - parseFloat(b[0])));
}

// "text @ px" for each non-decorative entry under minPx, so a failure names the offender.
export async function smallText(root: Locator, minPx: number): Promise<string[]> {
  return (await textSizes(root)).filter((e) => !e.decorative && parseFloat(e.px) < minPx).map((e) => `${e.text} @ ${e.px}`);
}

// Desktop-unchanged spot values (S0): the shell frame and panel, the first
// bordered page-level card, and the first Pills button. Captured at HEAD before
// any ui/app edit, so a later phone-only change cannot leak into 1280.
export type DesktopSpot = {
  framePad: string;
  panelRadius: string;
  panelBorder: string;
  card: { pad: string; radius: string; mb: string } | null;
  pillH: number | null;
};
export function desktopSpot(page: import("@playwright/test").Page): Promise<DesktopSpot> {
  return page.evaluate(() => {
    const cs = (el: Element) => getComputedStyle(el);
    const frame = cs(document.querySelector(".app-frame")!);
    const panel = cs(document.querySelector(".app-panel")!);
    const card = Array.from(document.querySelectorAll("main .tab-in > *, main section, main article")).find(
      (el) => cs(el).borderTopWidth === "1px" && cs(el).paddingLeft !== "0px",
    );
    const pill = document.querySelector('[role="group"] button[aria-pressed]');
    return {
      framePad: frame.padding,
      panelRadius: panel.borderRadius,
      panelBorder: panel.borderTopWidth,
      card: card ? { pad: cs(card).padding, radius: cs(card).borderRadius, mb: cs(card).marginBottom } : null,
      pillH: pill ? pill.getBoundingClientRect().height : null,
    };
  });
}
