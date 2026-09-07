# REPORT — OCR asked for the wrong language, and the outline showed it

- **Date:** 2026-09-07
- **Branch:** `fix/reading-ocr-language` (cut from `origin/main` @ `00587794`)
- **Predecessors:** `REPORT_reading_ocr_2026-09-06.md` (#9), `REPORT_reading_ocr_slides_2026-09-06.md` (#13)
- **Trigger:** first live run after Tesseract was installed on `203.185.144.41/deepwitya2`
- **Reproducer:** `Vectorless_RAG_Evolution.pptx` — 12 slides, 14.5 MB, Thai deck

---

## 1. What the live run showed

English on the slides read cleanly. Thai on the *same* slides came back as
Latin: `SudouuwuusiU`, `AD WAAIWAaVAUUAY`, `Tasva$iwdidudu`. A clean/garbled
split along language lines is the signature of OCR running English-only.

The table of contents was worse: `ita`, `2.`, `onl`, `z|`, `oll`, `ope`, `{ae`.

## 2. Diagnosis

### Two settings named "language", and I read the wrong one

| file | key | value on this deployment |
|---|---|---|
| `data/user/settings/main.yaml` | `system.language` | `en` ← what `_ocr_language` read |
| `data/user/settings/interface.json` | `language` | `th` ← what the person actually picked |
| `data/user/settings/interface.json` | `response_language` | `th` |

The interface is Thai — visible in the screenshot's own chrome
(*สารบัญ*, *ทดสอบฉัน*, *อ่านออกเสียง*). `system.language` stayed `en` because
#11's Thai default applies to **fresh** installs and this one predates it.

`deeptutor/services/settings/interface_settings.py` has exposed
`get_ui_language()` and `get_response_language()` the whole time. The docstring
I wrote even said "interface language" — the code just did not read it.

Reproduced locally before changing anything:

```
what OCR asks for : eng
actual UI language: th
response language : th
```

### Why local testing missed it

Every local run had passed `DEEPTUTOR_READING_OCR_LANGUAGE=tha+eng`
explicitly — proving Thai OCR *works*, never proving the default *chooses* it.
The one path every real deployment takes was the one path never exercised.

**This failure class deserves naming:** English-only OCR of Thai does not
error. It returns plausible-looking text, so no log, no status code and no test
assertion reports anything wrong. Only a human reading the output can tell.

### The outline was the same cause, compounded

OCR reads decoration as characters. Measured on this deck, the lines preceding
each real heading run **1–6 non-whitespace characters** while the headings run
**23–45**:

```
slide 8:  "๑" (1)  "oll" (3)  "2." (2)  "= _" (2)  "e" (1)
          "Phase 2 Deep Dive: การสืบค้นด้วยตรรกะเชิงวิเคราะห์" (45)
```

`synthesise_outline` took the literal first line, so the navigator advertised
the noise.

## 3. What changed

| file | change |
|---|---|
| `deeptutor/reading/ocr.py` | read `interface.json` via its own accessors; check `.traineddata` before OCR |
| `deeptutor/reading/extract.py` | `Extraction.from_ocr`; `min_chars` on the label rule |
| `deeptutor/reading/store.py` | pass `from_ocr` through to the outline |
| `tests/reading/test_ocr.py` | 32 → 43 tests |

Three things worth calling out:

1. **Both interface languages count.** UI language first, reply language
   second, English always last. An English UI does not mean English documents.
2. **A missing pack names its own package.** Tesseract fails the whole page
   when a requested language is absent and its error names a path, not a
   package. Checking the `.traineddata` present first turns that into
   `apt install tesseract-ocr-tha`.
3. **The stricter label rule applies to OCR'd units only**, and falls back to
   the old rule when nothing qualifies. A poor label beats a blank navigator
   row, and a legitimately short heading in a normal document still labels its
   section.

Two of the rewritten tests had been **passing for the wrong reason** — they
stubbed `load_config_with_main` while the code now reads `interface.json`, so
they were quietly asserting against this machine's real settings. They now pin
both accessors.

## 4. Verification

On the reported deck, **no environment override** — the path the deployment
actually takes:

```
language : tha+eng   (resolved, not passed)
units    : 12 slides   chars: 5,869   elapsed: 12.7 s
```

Headings that now read: *"ข้อจำกัดหลักของ Traditional RAG"*,
*"Vectorless RAG: จากการหาค่า สู่การเข้าใจโครงสร้าง"*,
*"Phase 2 Deep Dive: การสืบค้นด้วยตรรกะเชิงวิเคราะห์"*,
*"The Explainability Advantage: โปร่งใสและอ้างอิงได้ 100%"*,
*"สรุปกระบวนทัศน์: ทำไม Vectorless RAG คืออนาคตระดับ Enterprise?"*.

**Outline labels: 1 of 12 usable → 11 of 12.** The remaining one is slide 1, a
title slide drawn as art with no clean text anywhere on it.

| gate | result |
|---|---|
| `pytest tests/reading/` | 369 passed |
| `tests/reading/test_ocr.py` | 43 passed |
| `ruff check` / `ruff format --check` | clean |
| `scripts/precheck.sh --fast` | 7150 passed, 1 failed — the same `test_child_allocation_does_not_raise_parent_rss_plateau` that fails on `main` and passes in CI |

## 5. Follow-ups

- **Slide 1 stays noise.** A title slide rendered as artwork has no clean text
  to find; no label rule fixes that.
- **A per-material language override** would help a Thai user reading an
  English scan, and vice versa. The env var is deployment-wide today.
- Carried forward from #9/#13: `tessdata_fast` Thai spacing, and no background
  job for long documents.
