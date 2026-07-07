// N-best rescue for Web Speech results — the recognizer's runner-up
// hypotheses are free signal we were throwing away. When the top transcript
// garbles a navigation command ("ไฟหน้าหน่วยความจำ") the correct phrase
// ("ไปหน้าหน่วยความจำ") is very often sitting in alternative #2. Browser STT
// offers no vocabulary biasing, so this is the closest client-side
// equivalent: keep the top hypothesis unless it does NOT look like a page
// command while a lower-ranked one DOES.
//
// Deliberately conservative: normal conversation always keeps rank #1 — a
// lower alternative is only promoted when it matches the explicit
// verb+"หน้า" navigation shape AND names a known page, so the swap can only
// move us toward a command the server-side whitelist re-validates anyway.

const NAV_SHAPE = /(ไป|เปิด|พา|เข้า|กลับ|สลับ|ขอ)\s*(ที่|ยัง)?\s*(หน้า|page)/i;

/** Tokens (length ≥ 3) from manifest labels, for the "names a known page" check. */
export function labelTokens(labels: string[]): string[] {
  const out = new Set<string>();
  for (const label of labels) {
    for (const token of label.toLowerCase().split(/[\s()/—·,-]+/)) {
      if (token.length >= 3) {
        out.add(token);
        if (token.startsWith("หน้า") && token.length > 4) out.add(token.slice(4));
      }
    }
  }
  // Generic words match every phrase and would defeat the "names a known
  // page" check entirely (same lesson as the server-side matcher).
  out.delete("หน้า");
  out.delete("page");
  return [...out];
}

function looksLikeNavCommand(text: string, tokens: string[]): boolean {
  const t = text.toLowerCase();
  return NAV_SHAPE.test(t) && tokens.some((token) => t.includes(token));
}

/**
 * Choose the utterance to send from a recognizer's ranked alternatives.
 *
 * Rank #1 wins unless it is *nav-adjacent* — it already talks about a page
 * ("หน้า" or a known page name is in there) yet fails the full command
 * shape — while a lower-ranked alternative passes it. A top hypothesis with
 * no page reference at all is ordinary conversation and is never replaced.
 */
export function pickUtterance(alternatives: string[], labels: string[]): string {
  const ranked = alternatives.map((a) => a.trim()).filter(Boolean);
  if (ranked.length === 0) return "";
  if (ranked.length === 1) return ranked[0];
  const tokens = labelTokens(labels);
  const top = ranked[0].toLowerCase();
  const navAdjacent = top.includes("หน้า") || tokens.some((token) => top.includes(token));
  if (!navAdjacent || looksLikeNavCommand(ranked[0], tokens)) return ranked[0];
  return ranked.slice(1).find((a) => looksLikeNavCommand(a, tokens)) ?? ranked[0];
}
