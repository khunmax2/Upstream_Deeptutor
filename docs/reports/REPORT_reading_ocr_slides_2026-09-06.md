# REPORT — Immersive Reading: OCR for picture-only slide decks

- **Date:** 2026-09-06
- **Branch:** `feat/reading-ocr-slides` (cut from `origin/main` @ `7da51471`)
- **Predecessor:** `docs/reports/REPORT_reading_ocr_2026-09-06.md` (the scanned-PDF round, merged as #9)
- **Reported by:** Attapon, against `203.185.144.41/deepwitya2`
- **Reproducer:** `PageIndex_Vectorless_RAG_Architecture.pptx` — 10 slides, 11.6 MB, Thai deck

---

## 1. The report

A second upload failure on the same screen, right after #9 merged:

> `PageIndex_Vectorless_RAG_Architecture.pptx: PageIndex_Vectorless_RAG_Architecture.pptx: no extractable text`

Two defects visible in one line.

## 2. Diagnosis

### The deck is the scanned-PDF problem in a different format

```
entries: 65   slides: 10   media: 10   notes: 0
ppt/slides/slide1.xml   921 bytes,  0 <a:t> runs,  0 chars   (× 10)
ppt/media/image1..10.png            ~1.0–1.6 MB each
```

Each `slideN.xml` is a shell holding a single full-bleed `<p:pic>`. The deck was
exported from a design tool, so **the slides are pictures**. No text run exists
to extract.

### Why #9's recovery did not catch it

The PDF fallback hooks `extract_material`'s "all units empty" check. PPTX never
reaches it:

```
_extract_slides(source)
  → _shared_extract(source)
  → extract_text_from_path → _extract_pptx → "" → EmptyDocumentError
  → ReadingError raised here, before extract_material's empty check
```

### The doubled filename

Pre-existing, and already logged as a follow-up in the #9 report.
`EmptyDocumentError` is constructed as `f"{filename}: no extractable text"`, and
`_shared_extract` prefixed `source.name` onto it a second time.

## 3. What was built

| file | change |
|---|---|
| `deeptutor/reading/ocr.py` | `recover_slides_with_ocr` + OOXML readers; shared "no engine" guidance |
| `deeptutor/reading/extract.py` | slide branch recovers on `EmptyDocumentError`; filename no longer doubled |
| `tests/reading/test_ocr.py` | 21 → 32 tests |

**Pictures are read out of the package, not rendered.** For a deck whose every
slide is already an image, rendering through LibreOffice would only redraw what
is sitting in `ppt/media/`. Reading the parts directly keeps the whole feature
dependency-free.

### Two details that carry the correctness

1. **Slide order comes from `sldIdLst`, not file names.** `slideN.xml` numbers
   are creation order; a reordered deck would otherwise attribute each slide's
   text to the wrong locator — the same misalignment the PDF path refuses to
   risk. Numeric file order is the fallback, so slide10 follows slide9.
2. **Only "holds no text" routes to OCR.** `_shared_extract` re-raises
   `from exc`, so the extractor's exception type is still on `__cause__`: an
   `EmptyDocumentError` recovers, a corrupt package still reports being corrupt.
   Read from the chain, not matched against the message — that message is
   user-facing copy and free to change.

### Upscaling

`get_pixmap` renders an image at its *declared* size at 72 dpi, which for a
slide picture sits well under its own pixel count (this deck: 1032 px rendered
vs 1376 px native). Pictures are scaled to a 2400 px target width — the pixel
width A4-at-300-dpi works out to, matching the PDF path — and small text OCRs
better upscaled than at native size.

## 4. Verification

**On the reported deck**, `tha+eng`:

```
extractor: pptx+ocr:tesseract | unit: slide | units: 10 | chars: 4,654
elapsed  : 9.7 s
```

Recovered slide titles include *"สถาปัตยกรรม RAG ไร้เวกเตอร์"*,
*"ความคล้ายคลึง(Similarity) ≠ ความเกี่ยวข้อง(Relevance)"*,
*"การจัดทำดัชนีด้วยโครงสร้างต้นไม้ (Hierarchical Tree Index)"*,
*"สถาปัตยกรรม 2 ระยะ (Two-Phase Operation)"*,
*"นิเวศการใช้งานที่ครอบคลุม (Deployment Ecosystem)"*.

Decorative graphics contribute noise between the headings; the substance of
every slide is recovered and every slide is addressable.

**Language matters more here than for the PDF.** OCR'ing this deck with `eng`
alone returns mojibake. The default already handles it — `_ocr_language()`
derives from the interface language, and this fork now defaults a fresh install
to Thai (#11), so `tha+eng` is what a Thai install asks for without configuring
anything.

**Gates**

| gate | result |
|---|---|
| `pytest tests/reading/` | 358 passed |
| `tests/reading/test_ocr.py` | 32 passed (0 skipped, Tesseract present) |
| `ruff check` / `ruff format --check` | clean |
| `scripts/precheck.sh --fast` | 7139 passed, 1 failed — the same `test_child_allocation_does_not_raise_parent_rss_plateau` that fails on `main` and passes in CI |

## 5. Follow-ups, not done here

- **A DOCX or XLSX of scanned pages takes the same dead end.** Neither was
  reported, and neither has the one-picture-per-unit shape that makes the slide
  mapping honest, so neither is guessed at here.
- **Still no background job.** A 200-slide picture deck would hold the upload
  request for minutes; the wall-clock budget bounds the wait but does not move
  the work off the request.
- **`tessdata_fast` Thai spacing**, carried over from the #9 report.
