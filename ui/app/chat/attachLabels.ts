// The pure copy builders for Phase 39 (39-UI-SPEC "Copywriting Contract"). No React,
// so every string and pre-check is unit-tested without a browser. Server strings
// (destination, summary) are passed through verbatim, never composed here.

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

const EXT_KIND: Record<string, "csv" | "pdf" | "image"> = {
  csv: "csv",
  pdf: "pdf",
  png: "image",
  jpg: "image",
  jpeg: "image",
  webp: "image",
};
export const ACCEPT_ATTR =
  ".csv,.pdf,.png,.jpg,.jpeg,.webp,text/csv,application/pdf,image/png,image/jpeg,image/webp";

export type ClientKind = "csv" | "pdf" | "image";

/** What the client can tell from the extension alone (the server checks magic bytes). */
export function fileKind(name: string): ClientKind | null {
  const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
  return EXT_KIND[ext] ?? null;
}

const TYPE_MSG = "monai reads CSV, PDF, PNG, JPEG and WebP files. Choose one of those.";

/** Courtesy check on selection; the backend stays authoritative (D-06, D-06a). */
export function precheck(file: { name: string; size: number }): string | null {
  if (fileKind(file.name) === null) return TYPE_MSG;
  if (file.size === 0) return "That file is empty. Choose another file.";
  if (file.size > MAX_UPLOAD_BYTES)
    return `That file is ${(file.size / 1048576).toFixed(1)} MB. The limit is 10 MB. Choose a smaller file.`;
  return null;
}

// --- Locality (D-15, DOC-06) -----------------------------------------------

export type Locality = { local: boolean; destination: string | null };
export type LocalityLine = { lead: string; text: string };

export const LOCALITY_EYEBROW = "WHERE YOUR FILE GOES";
export const LOCALITY_LOADING = "Checking where your file would go…";
export const LOCALITY_FAILED = "Couldn't check where files are sent.";

export function localityLines(loc: Locality, kind: ClientKind | null): LocalityLine[] {
  if (loc.local) return [{ lead: "", text: "Stays on this computer." }];
  const d = loc.destination ?? "an outside service";
  const csv = {
    lead: "CSV and text PDF:",
    text: `Parsed on this computer. Its text is sent to ${d} when you ask about it.`,
  };
  const img = { lead: "Image or scan:", text: `The image is sent to ${d} to be read.` };
  // A PDF may be text or a scan, and nothing is chosen yet: show both.
  return kind === "csv" ? [csv] : kind === "image" ? [img] : [csv, img];
}

// --- Upload errors ---------------------------------------------------------

export function uploadErrorText(status: number | "network", detail?: string): string {
  if (status === 413) return "That file is over the 10 MB limit. Choose a smaller file.";
  if (status === 415)
    return "monai reads CSV, PDF, PNG, JPEG and WebP files. This one isn't any of those.";
  if (status === 401 || status === 403)
    return `Couldn't attach the file: the server refused it (${status}). Nothing was added to your records.`;
  const d = detail ?? (status === "network" ? "Network error" : `HTTP ${status}`);
  return `Couldn't attach the file: ${d}. Nothing was added to your records.`;
}

// --- Chips -----------------------------------------------------------------

export type ChipState = "uploading" | "ok" | "llm_read" | "refused" | "needs_password" | "failed";

export type AttachChip = {
  localId: string;
  attachmentId: string | null;
  filename: string;
  /** Client kind while uploading, then the server's: csv | pdf_text | pdf_scanned | image. */
  kind: string | null;
  state: ChipState;
  summary: string;
  rowCount: number;
  purgedAt: string | null;
  messageId: string | null;
};

export const KIND_LABEL: Record<string, string> = {
  csv: "CSV",
  pdf_text: "PDF",
  pdf_scanned: "Scanned PDF",
  image: "Image",
};
export const PURGED_SUFFIX = " · original file removed";
export const PURGED_TITLE =
  "The original file was deleted 7 days after upload. The text and rows read from it are still here.";

export type ChipTone = "plain" | "warm" | "refused";

export function chipText(c: AttachChip): {
  status: string;
  detail: string | null;
  tone: ChipTone;
  purged: boolean;
} {
  const purged = c.purgedAt !== null;
  switch (c.state) {
    case "uploading":
      return {
        status: c.kind === "image" ? "Reading the image…" : "Uploading…",
        detail: null,
        tone: "plain",
        purged,
      };
    case "ok":
      return { status: "Ready", detail: c.summary || null, tone: "plain", purged };
    case "llm_read":
      return { status: "LLM-read", detail: c.summary || null, tone: "warm", purged };
    case "refused":
      return { status: "Can't propose rows", detail: c.summary || null, tone: "refused", purged };
    case "needs_password":
      return { status: "Needs a password", detail: "Enter it in the Attach panel.", tone: "warm", purged };
    case "failed":
      return { status: "Upload failed", detail: c.summary || null, tone: "refused", purged };
  }
}

const rows = (n: number) => `${n} ${n === 1 ? "row" : "rows"}`;

/** Status words for the read-only pill under a sent message (UI-SPEC section 4). */
export function pillStatus(c: AttachChip): string {
  return c.state === "ok"
    ? `${KIND_LABEL[c.kind ?? ""] ?? "File"} · ${rows(c.rowCount)}`
    : chipText(c).status;
}

export function placeholderFor(n: number): string | null {
  if (n <= 0) return null;
  return n === 1
    ? "Ask about this file, or ask me to propose its rows…"
    : "Ask about these files, or ask me to propose their rows…";
}

// --- Upload card (D-22) ----------------------------------------------------

const TAILS: Record<string, string> = {
  confirmed: "Approved in Inbox",
  rejected: "Rejected in Inbox",
  expired: "Expired",
  superseded: "Replaced by a newer proposal",
  missing: "Replaced by a newer proposal",
};

/** `status` undefined is the in-view turn, which is pending. */
export function cardSentence(
  n: number,
  k: number,
  status: string | undefined
): { lead: string; tail: string; linked: boolean } {
  const lead = `${rows(n)} proposed, ${k} flagged — `;
  const tail = TAILS[status ?? ""];
  return tail ? { lead, tail, linked: false } : { lead, tail: "Review in Inbox", linked: true };
}

export function trustLine(meta: { invariant?: string | null; llm_read?: boolean }): string {
  if (meta.llm_read) return "Read by the model from an image. Check every row against the original.";
  if (meta.invariant === "balance verified")
    return "Opening balance plus these rows matches the closing balance printed on the statement.";
  if (meta.invariant === "running balance verified")
    return "Opening balance, every running balance and the closing balance match the statement.";
  return "A CSV has no balance to check. Review the rows before approving.";
}

export function cardTrustLine(
  status: string | undefined,
  meta: { invariant?: string | null; llm_read?: boolean }
): string | null {
  if (status === "rejected" || status === "superseded" || status === "missing") return null;
  if (status === "expired") return "Ask me to propose the rows again.";
  return trustLine(meta);
}

// --- Password, storage and announcements ------------------------------------

export const ACCOUNT_STORAGE_KEY = "monai.attach.account";
export const PASSWORD_HINT = "Used once to open this file. monai doesn't store it.";
export const PASSWORD_WRONG = "That password didn't open the file. Check it and try again.";

export const announce = {
  attached: (f: string, summary: string) => `${f} attached. ${summary}`,
  needsPassword: (f: string) => `${f} is password protected. Enter its password.`,
  unreadable: (f: string, summary: string) => `Couldn't read ${f}. ${summary}`,
  cancelled: (f: string) => `Upload of ${f} cancelled.`,
  removed: (f: string) => `Removed ${f} from your question.`,
};
