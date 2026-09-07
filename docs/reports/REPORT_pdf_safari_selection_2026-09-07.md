# REPORT — PDF text was not selectable in Safari

- **Date:** 2026-09-07
- **Branch:** `fix/pdf-text-layer-safari` (cut from `origin/main` @ `d9de77fb`)
- **Reported by:** Attapon — *"ถ้าเปิดกับ safari นั้น ไม่สามารถคลุมดำที่ตัวข้อความได้"*
- **Environment:** Safari 26.6.2 (`AppleWebKit/605.1.15`), pdfjs-dist 6.2.108

---

## 1. Reproduction

Safari was driven directly over Apple Events (`osascript … do JavaScript`), on
the same document and the same dev server that works in Chrome:

| measurement | Chrome | Safari |
|---|---|---|
| `[data-reader-unit]` pages | 9 | 9 |
| `.textLayer` elements | 9 | 9 |
| spans per layer | `[19,126,0,…]` | **`[0,0,0,0,0,0,0,0,0]`** |
| canvases painted | yes | yes |

The page looked completely normal in Safari. Nothing was selectable on it.

## 2. Two independent WebKit divergences, stacked

### 2.1 `getTextContent()` threw

`--total-scale-factor` was unset on every layer, which places the failure at or
before the first `await` in `buildTextLayer`. Running pdf.js step by step in the
Safari page isolated it exactly:

```
import ok → worker set → getDocument ok pages=9 → getPage ok
getTextContent → TypeError: undefined is not a function (near '...t of e...')
  at getTextContent@…/pdf.min.mjs:26:258421
```

The minified source at that offset:

```js
async getTextContent(t = {}) {
  const e = this.streamTextContent(t), i = { items: [], … };
  for await (const t of e) { … }     // ← '...t of e...'
  return i;
}
```

`for await … of` a `ReadableStream` needs
`ReadableStream.prototype[Symbol.asyncIterator]`. Confirmed in that Safari:

```json
{"readableStreamAsyncIterator":"undefined","hasValues":"undefined"}
```

WebKit has never shipped it. Chrome and Firefox have.

### 2.2 Every span was `font-size: 0`

With text extraction shimmed, spans appeared — and still could not be selected:

```json
{"fontSize":"0px","spanRect":{"w":null,"h":null},
 "layerVars":{"minFont":"0","textScale":"calc(0.576… * 0)"},
 "computed":{"transform":"matrix(infinity, 0, 0, …"}}
```

pdf.js measures the smallest font the browser will actually render
(`TextLayer.#ensureMinFontSizeComputed`, `pdf.mjs:15132`) and publishes it as
`--min-font-size`:

```js
const div = document.createElement("div");
div.style.opacity = 0; div.style.lineHeight = 1; div.style.fontSize = "1px";
div.style.position = "absolute"; div.textContent = "X";
document.body.append(div);
this.#minFontSize = div.getBoundingClientRect().height;
```

Run verbatim in both browsers:

| | measured height |
|---|---|
| Chrome | **1** |
| Safari | **0** |

Zero propagates: `--text-scale-factor: calc(scale * 0)` → `font-size: 0` on
every span, and `--min-font-size-inv: calc(1 / 0)` → `transform: scale(infinity)`.
A fully populated, correctly positioned text layer of zero-sized boxes.

## 3. Why nobody noticed

`PdfPage` renders the canvas and the text layer through `Promise.allSettled` and
reports a failure only when **both** reject. That is a reasonable rule — either
half alone still leaves a usable page — but it means a text layer that never
built produces no error, no warning and no visual difference, while taking
selection, highlighting, annotations and every selection-gated reading action
with it.

## 4. What changed

| file | change |
|---|---|
| `web/lib/readable-stream-async-iterator.ts` | **new** — spec-shaped `values()` / `Symbol.asyncIterator` shim |
| `web/lib/pdfjs-loader.ts` | install the shim before importing pdf.js |
| `web/components/reading/PdfPage.tsx` | repair a non-positive `--min-font-size`; log one-sided render failures |
| `web/tests/readable-stream-async-iterator.test.ts` | **new** — 5 tests |

Both fixes are conditional. The shim is feature-detected, so Chrome and Firefox
keep their native implementation. The font-size repair runs only when the
measurement is not positive, so pdf.js's intent — compensating for a real
browser minimum — survives wherever the probe works.

The shim releases the reader's lock on **every** exit path, including the final
chunk. pdf.js drains a text stream to completion and never calls `return()`; a
lock retained past the last chunk would fail the next read of that page.

## 5. Verification, in Safari, after the fix

| | before | after |
|---|---|---|
| `--min-font-size` | 0 | 1 |
| span `font-size` | 0px | 57.64px |
| span box | NaN | 249 × 56 |
| `getSelection().toString()` | — | "Adaptive" |
| translate ×3 + vocabulary buttons | `disabled` | **enabled** |
| spans per layer | `[0,0,0,…]` | `[19,126,0,…]` (matches Chrome) |

**Gates**

| gate | result |
|---|---|
| `npm run test:node` | 1102 passed (1097 before) |
| `npx tsc --noEmit` | clean |
| `npm run lint` | 0 errors, 76 pre-existing warnings |
| `npm run i18n:check` | exit 0 (same as `main`) |

## 6. Follow-ups

- **The zero measurement is arguably a pdf.js bug**, and a small isolated diff —
  worth reporting upstream to pdf.js rather than only carrying the repair here.
- **A one-sided render failure is logged but not surfaced.** Whether the reader
  should tell the user "this page has no selectable text" is a product call, not
  made here.
- **No automated Safari coverage.** These two divergences are invisible to a
  Chromium-only test suite; nothing added here changes that.
