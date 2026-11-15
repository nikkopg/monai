"use client";

import { tokens } from "../styles";

// Pill segmented control shared by the Cashflow net worth card (1Y/3Y/All,
// Total/Split) and the Cashflow card (Week/Month/Year). `dark` is for
// the ink hero card; `small` is the light palette at the compact dark sizes;
// `label` names the group for assistive tech; `tap` gives each button the
// 32px (44px on touch) hit target Investments requires.
export default function Pills<T extends string>({
  options,
  value,
  onChange,
  dark = false,
  small = false,
  label,
  tap = false,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  dark?: boolean;
  small?: boolean;
  label?: string;
  tap?: boolean;
}) {
  const compact = dark || small;
  return (
    <div
      {...(label ? { role: "group", "aria-label": label } : {})}
      style={{
        display: "flex",
        gap: compact ? 2 : 6,
        background: dark ? "rgba(242,239,232,.08)" : "#efece4",
        border: dark ? "none" : `1px solid ${tokens.color.border2}`,
        borderRadius: 999,
        padding: compact ? 3 : 4,
      }}
    >
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={active}
            {...(tap ? { className: "coarse-tap" } : {})}
            onClick={() => onChange(opt.value)}
            style={{
              border: "none",
              borderRadius: 999,
              ...(tap ? { minHeight: 32 } : {}),
              padding: compact ? "4px 10px" : "7px 15px",
              fontSize: compact ? 12 : 13,
              fontWeight: active ? 600 : 500,
              cursor: "pointer",
              color: dark
                ? active ? tokens.color.ink : tokens.color.inkTextMuted
                : active ? tokens.color.inkText : tokens.color.muted3,
              background: active ? (dark ? tokens.color.inkText : tokens.color.ink) : "transparent",
              transition: "all .2s ease",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
