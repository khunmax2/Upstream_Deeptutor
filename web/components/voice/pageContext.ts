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
): { path: string; page?: string; summary: string; buttons: string[] } {
  const outline: PageOutline = {
    path: window.location.pathname,
    pageName,
    title: document.title,
    headings: grabTexts("h1, h2, h3", exclude),
    navLinks: grabTexts("nav a, aside a, [role='navigation'] a", exclude),
    tabs: grabTexts("[role='tab']", exclude),
    buttons: grabTexts("button, [role='button'], a[role='menuitem']", exclude),
  };
  // `page` and `buttons` ride as structured fields (not only inside the
  // summary prose): `page` answers "ตอนนี้อยู่หน้าไหน" deterministically and
  // `buttons` is what click-by-name resolves spoken names against. The
  // buttons list comes from the SAME collector the click executor uses, so
  // every name the server can approve is guaranteed pressable.
  return {
    path: outline.path,
    page: pageName,
    summary: formatPageContext(outline),
    buttons: cleanItems(visibleClickables(exclude).map((c) => c.label)),
  };
}

// Everything a finger could tap: real buttons/tabs, and links — settings-hub
// style cards are <Link href> around a heading, not <button>. Main-content
// clickables are listed before nav/sidebar ones so, under the caps, the page's
// own actions win over the ever-present sidebar links.
const CLICKABLE_SELECTOR =
  "button, [role='button'], [role='tab'], a[role='menuitem'], a[href]";

// A card's whole text ("LlamaIndex พร้อมใช้งาน Local vector retrieval…") is
// unmatchable by voice; past this length we fall back to the card's first
// text chunk, which is its visible title.
const MAX_WHOLE_LABEL_CHARS = 40;

/** First rendered text chunk inside *el* — a card's title, whatever tag it is. */
function firstTextChunk(el: HTMLElement): string {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const text = (node.textContent || "").replace(/\s+/g, " ").trim();
    if (text.length >= 2) return text;
  }
  return "";
}

/** Short spoken-friendly label for a clickable: aria-label, else the heading
 * inside it, else its full text when short, else its first text chunk (card
 * titles are often plain <span>s — the Knowledge-Center engine cards). */
function clickableLabel(el: HTMLElement): string {
  const aria = el.getAttribute("aria-label") || "";
  const heading = el.querySelector("h1, h2, h3, h4, h5, h6")?.textContent || "";
  const full = (el.textContent || "").replace(/\s+/g, " ").trim();
  const text =
    aria.trim() ||
    heading.replace(/\s+/g, " ").trim() ||
    (full.length <= MAX_WHOLE_LABEL_CHARS ? full : firstTextChunk(el) || full);
  return text.slice(0, MAX_ITEM_CHARS);
}

/**
 * The visible clickable elements (outside `exclude`) with their labels —
 * single source of truth for BOTH the streamed `buttons` context and the
 * click executor, so reporting and acting can never disagree.
 */
function visibleClickables(exclude: Element | null): { el: HTMLElement; label: string }[] {
  const main: { el: HTMLElement; label: string }[] = [];
  const nav: { el: HTMLElement; label: string }[] = [];
  for (const el of Array.from(document.querySelectorAll<HTMLElement>(CLICKABLE_SELECTOR))) {
    if (exclude && exclude.contains(el)) continue;
    if (!isVisible(el)) continue;
    const label = clickableLabel(el);
    if (!label) continue;
    (el.closest("nav, aside, [role='navigation']") ? nav : main).push({ el, label });
  }
  return [...main, ...nav];
}

/**
 * The page's main scrollable container. DeepTutor's shell is
 * `h-screen overflow-hidden`, so `window` almost never scrolls — the real
 * scroller is some inner div. Pick the visible scrollable element (outside
 * the widget) with the largest viewport area; fall back to the document.
 */
function mainScrollable(exclude: Element | null): HTMLElement | null {
  const doc = document.scrollingElement as HTMLElement | null;
  let best: HTMLElement | null = null;
  let bestArea = 0;
  for (const el of Array.from(document.querySelectorAll<HTMLElement>("*"))) {
    if (exclude && exclude.contains(el)) continue;
    if (el.scrollHeight <= el.clientHeight + 40) continue;
    const style = getComputedStyle(el);
    if (style.overflowY !== "auto" && style.overflowY !== "scroll") continue;
    if (!isVisible(el)) continue;
    const rect = el.getBoundingClientRect();
    const area = rect.width * rect.height;
    if (area > bestArea) {
      best = el;
      bestArea = area;
    }
  }
  if (best) return best;
  if (doc && doc.scrollHeight > doc.clientHeight + 40) return doc;
  return null;
}

/** Voice scroll: direction is one of scroll_down/up/bottom/top. */
export function scrollByVoice(direction: string, exclude: Element | null): boolean {
  const el = mainScrollable(exclude);
  if (!el) return false;
  const page = el.clientHeight * 0.75;
  if (direction === "scroll_down") el.scrollBy({ top: page, behavior: "smooth" });
  else if (direction === "scroll_up") el.scrollBy({ top: -page, behavior: "smooth" });
  else if (direction === "scroll_bottom") el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  else if (direction === "scroll_top") el.scrollTo({ top: 0, behavior: "smooth" });
  else return false;
  return true;
}

/**
 * Click the visible element whose label matches *name* (exact normalised
 * match first, then substring). Returns whether something was clicked. Uses
 * the same collector as collectPageContext, so the server can only name what
 * the caller could see.
 */
export function clickVisibleByText(name: string, exclude: Element | null): boolean {
  const norm = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();
  const target = norm(name);
  if (!target) return false;
  let exact: HTMLElement | null = null;
  let partial: HTMLElement | null = null;
  for (const { el, label } of visibleClickables(exclude)) {
    const text = norm(label);
    if (text === target && !exact) exact = el;
    else if (!partial && (text.includes(target) || target.includes(text))) partial = el;
  }
  const chosen = exact ?? partial;
  chosen?.click();
  return Boolean(chosen);
}
