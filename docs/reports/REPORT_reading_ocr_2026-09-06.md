# REPORT — Immersive Reading: OCR fallback for scanned PDFs

- **Date:** 2026-09-06
- **Branch:** `feat/reading-ocr-fallback` (cut from `main` @ `e0bd74a5`)
- **Base commit:** `e0bd74a5` chore(dev): pin local development to Python 3.13 and declare ruff (#5)
- **Reported by:** Attapon, against the deployed instance at `203.185.144.41/deepwitya2`
- **Reproducer:** `26004947 - หนังสือส่งมอบงาน.pdf` — 5 pages, 431 KB, Thai signed handover letter

---

## 1. The report

Uploading a PDF in **อ่านกับติวเตอร์** (Immersive Reading) failed with:

> `26004947 - หนังสือส่งมอบงาน.pdf: no readable text could be extracted.
> A scanned document needs OCR before it can be read here.`

## 2. Diagnosis

The message was **accurate**, which is what made the report worth taking
seriously rather than dismissing: the code was behaving exactly as designed, and
the design had no way out.

```
POST /api/reading/materials
  → ReadingStore.ingest()          store.py:262
  → extract_material()             extract.py:80
  → _extract_pdf()                 extract.py:124   page.get_text() per page
  → all pages empty → ReadingError extract.py:101
  → HTTP 400                       api/routers/reading.py:125
```

No fallback of any kind: not pypdf, not another engine, not OCR.

**The real gap was architectural.** The repo already ships an engine-pluggable
parse layer (`deeptutor/services/parsing/`, with `ParseService` and MinerU /
Docling / PyMuPDF4LLM adapters, all carrying `do_ocr` / `is_ocr` flags). It was
wired into the RAG pipelines only. `deeptutor/reading/` called
`extract_material()` directly and never touched it — so the same file could be
parsed by the knowledge-base path while being refused by the reading path.

**The file itself** was confirmed a true scan before writing any code, with a
probe that reports per-page text/image/vector-path counts:

| page | text chars | images | vector paths |
|-----:|-----------:|-------:|-------------:|
| 1–5  | 0          | 1      | 0            |

One full-page image per page, no text, no outlined vectors — a scan, not a
text-to-outlines export. Both would need OCR, but the distinction mattered:
it ruled out a Thai font/encoding defect in PyMuPDF, which was the competing
hypothesis.

## 3. What was built

One new file carries the whole feature; the upstream files take four lines
between them, per fork policy §3.

| file | change |
|---|---|
| `deeptutor/reading/ocr.py` | **new** — the entire fallback |
| `deeptutor/reading/extract.py` | `raw_bytes` field on `Extraction`; PDF branch calls the recovery before raising |
| `deeptutor/reading/store.py` | write `extraction.raw_bytes or data` for the raw view |
| `tests/reading/test_ocr.py` | **new** — 21 tests |

### Two invariants the design is built around

1. **The page grid is the locator space.** A PDF is the one format the reader
   renders faithfully, so `locator == physical page number`, and an annotation
   is stored normalised against that page's box. A recovery returning flat
   markdown would put unit 7 on page 3 and land every highlight wrong. Every
   provider emits *exactly* `page_count` units in page order, or declines.
   Engine blocks are grouped by `page_idx`; out-of-range blocks are dropped, not
   clamped — the rule `_pdf_outline` already applies to stale bookmarks.

2. **Selection happens in the browser.** `web/components/reading/PdfPage.tsx`
   builds its selection surface from pdf.js `getTextContent()`. Text known only
   server-side would leave select → highlight → ask dead on exactly these
   documents. The Tesseract provider therefore returns a **rebuilt PDF with an
   invisible OCR text layer**, which the store writes for the raw view. One pass
   produces both halves: `pdfocr_tobytes()` welds the layer in, and reading that
   page back yields the unit text.

### Provider order

1. The operator's configured parse engine, **only** when it is one that actually
   OCRs (MinerU, Docling). They read Thai layout better than Tesseract, and an
   operator who configured one has already stated a preference.
2. PyMuPDF's built-in Tesseract binding — no new Python dependency, since
   PyMuPDF is already core.

A heavy engine that is missing, misconfigured, or lacking models **declines**
rather than raising, so it can never cost the user the Tesseract path that would
have worked. When nothing can run, the original two sentences are preserved
verbatim (the API contract test and the UI copy both depend on them) and the
operator-facing fix is appended.

### Configuration

Environment-only, deliberately: this path runs *only* for a document that would
otherwise be rejected, so there is no default behaviour to protect and no
settings-UI surface to maintain.

| variable | default |
|---|---|
| `DEEPTUTOR_READING_OCR` | on; set `0` to refuse OCR |
| `DEEPTUTOR_READING_OCR_LANGUAGE` | interface language + `eng` (a Thai install asks for `tha+eng`) |
| `DEEPTUTOR_READING_OCR_DPI` | `300` (clamped 72–600) |
| `DEEPTUTOR_READING_OCR_MAX_SECONDS` | `300` — the upload is synchronous, so this bounds the wait |

## 4. Verification

**On the reported file**, with `tesseract 5.5.3` + `tha.traineddata`
(tessdata_fast):

```
extractor  : pymupdf+ocr:tesseract
unit/render: page / pdf     raw view: True
units      : 5              chars: 3,573
rebuilt pdf: 787,542 bytes  (original 441,505)
elapsed    : 6.5 s
```

Store round-trip: material ingests, `unit=page`, `render_mode=pdf`, and the
stored raw PDF reports **86 selectable words on page 1** — which is what pdf.js
hands the selection layer, so highlighting works on this scan.

Recovered page 1 opens:
*"หนังสือส่งมอบงาน … เรื่องขอส่งมอบงานตามใบจ้าง PO26004947 เรียนคณะกรรมการตรวจรับพัสดุ…"*

Pages 1–3 (typed document body) read well. Pages 4–5 are photographs — an ID
card and a signature page — and OCR them as noise. That is the expected ceiling
of OCR on photographs, not a defect.

**Gates**

| gate | result |
|---|---|
| `pytest tests/reading/` | 347 passed |
| `tests/reading/test_ocr.py` | 21 passed (0 skipped, with Tesseract present) |
| `ruff check` / `ruff format --check` | clean |
| full suite vs. `main` | **identical** — the same 26 pre-existing failures on both trees, none in reading |

The 26 pre-existing failures (websocket, CORS, sandbox, learning API) were
confirmed by capturing the failure list on both trees and diffing it. They are
unrelated to this change and predate the branch.

## 5. Deployment note

The server at `203.185.144.41/deepwitya2` needs an OCR engine installed before
this helps there:

```bash
apt install tesseract-ocr tesseract-ocr-tha
```

Without it the upload still fails — but the message now names the exact fix
instead of dead-ending.

## 6. Follow-ups, not done here

- **`tessdata_fast` drops some Thai word spacing** ("วันที7 สิงหาคม2569").
  `tessdata_best` for `tha` is more accurate and roughly 4× larger; worth
  measuring on a Thai corpus before choosing a default.
- **A long scan blocks the upload request.** The wall-clock budget bounds it,
  but a 200-page scan belongs on a background job with progress, not a
  synchronous POST.
- **Duplicated filename in a shared-extractor error** —
  `blank.txt: blank.txt: no extractable text`. `_shared_extract` prefixes
  `source.name` onto an exception whose message already carries it
  (`extract.py:376`). Cosmetic, pre-existing, out of scope here.
