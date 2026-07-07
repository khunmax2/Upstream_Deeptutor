// Current-screen context for the voice call — the "read" half of voice UI
// control. The widget sits in the root layout, so whatever page the caller is
// on, its DOM is visible here. Before each spoken turn we serialise a compact
// text outline of that DOM (headings, nav links, tabs, buttons) and stream it
// to the voice layer as a `ui_context` control frame; the model then answers
// "หน้านี้มีเมนูอะไรบ้าง" from the real screen instead of guessing.
//
// Read-only by design: we serialise text the page already shows and never
// read input/textarea *values* (form contents, keys, passwords stay out of
// the prompt). Acting on the page remains the manifest whitelist's job.
//
// Split in two so the formatting/capping logic is testable under node:test
// (no DOM): `collectPageOutline` reads the DOM, `formatPageContext` is pure.

export interface PageOutline {
  path: string;
  /** Human page name from the UI_PAGES manifest (when the path matches). */
  pageName?: string;
  title: string;
  headings: string[];
  navLinks: string[];
  tabs: string[];
  buttons: string[];
}

// The whole control frame must stay under the server's 8K frame cap
// (MAX_MANIFEST_BYTES); the stored summary is capped server-side at 3000
// chars — stay under both with margin.
export const MAX_SUMMARY_CHARS = 2400;
const MAX_ITEM_CHARS = 60;
const MAX_ITEMS_PER_SECTION = 25;

function cleanItems(items: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of items) {
    const text = raw.replace(/\s+/g, " ").trim().slice(0, MAX_ITEM_CHARS);
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push(text);
    if (out.length >= MAX_ITEMS_PER_SECTION) break;
  }
  return out;
}

/** Pure formatter: outline → capped one-string summary (node-testable). */
export function formatPageContext(o: PageOutline): string {
  const sections: [string, string[]][] = [
    ["หัวข้อ", cleanItems(o.headings)],
    ["เมนู/ลิงก์", cleanItems(o.navLinks)],
    ["แท็บ", cleanItems(o.tabs)],
    ["ปุ่ม", cleanItems(o.buttons)],
  ];
  const lines: string[] = [];
  // Current-page identity first and in plain words — the model must answer
  // "ตอนนี้อยู่หน้าไหน" from here, not from stale navigation turns in the
  // conversation history (the caller can click around by hand at any time).
  const pageName = (o.pageName || "").replace(/\s+/g, " ").trim();
  if (pageName) lines.push(`หน้าปัจจุบัน: ${pageName.slice(0, MAX_ITEM_CHARS)} (${o.path})`);
  const title = o.title.replace(/\s+/g, " ").trim();
  if (title) lines.push(`ชื่อหน้า: ${title.slice(0, MAX_ITEM_CHARS)}`);
  for (const [label, items] of sections) {
    if (items.length) lines.push(`${label}: ${items.join(" | ")}`);
  }
  return lines.join("\n").slice(0, MAX_SUMMARY_CHARS);
}

function isVisible(el: Element): boolean {
  return (el as HTMLElement).offsetParent !== null;
}

function grabTexts(selector: string, exclude: Element | null): string[] {
  const out: string[] = [];
  document.querySelectorAll(selector).forEach((el) => {
    if (exclude && exclude.contains(el)) return; // never describe our own panel
    if (!isVisible(el)) return;
    const text = el.textContent || (el as HTMLElement).getAttribute?.("aria-label") || "";
    if (text.trim()) out.push(text);
  });
  return out;
}

/**
 * Read the visible page into a `{path, summary}` context ready to send as a
 * `ui_context` frame. `exclude` is the widget's own root element so the call
 * panel never describes itself; `pageName` is the human label for the current
 * path (from the UI_PAGES manifest) so "which page am I on" has a plain-words
 * answer.
 */
export function collectPageContext(
  exclude: Element | null,
  pageName?: string,
): { path: string; page?: string; summary: string } {
  const outline: PageOutline = {
    path: window.location.pathname,
    pageName,
    title: document.title,
    headings: grabTexts("h1, h2, h3", exclude),
    navLinks: grabTexts("nav a, aside a, [role='navigation'] a", exclude),
    tabs: grabTexts("[role='tab']", exclude),
    buttons: grabTexts("button, [role='button'], a[role='menuitem']", exclude),
  };
  // `page` rides as its own field (not only inside the summary text) so the
  // server can answer "ตอนนี้อยู่หน้าไหน" deterministically, without the LLM.
  return { path: outline.path, page: pageName, summary: formatPageContext(outline) };
}
