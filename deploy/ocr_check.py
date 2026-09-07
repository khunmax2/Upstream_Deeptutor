"""Prove the OCR fallback actually works in this image.

`deeptutor/reading/ocr.py` runs only for a document with no text layer at all,
so a normal upload never exercises it and a missing Tesseract stays invisible
until someone hands the reader a scanned PDF. This builds exactly that document
— a PDF whose only content is a picture of text — and pushes it through the
real extractor.

Run inside the container:
    docker exec -w /app -e PYTHONPATH=/app deeptutor2 python3 /tmp/ocr_check.py
"""

from __future__ import annotations

import sys


def _image_only_pdf(text: str, fontfile: str | None) -> bytes:
    """A one-page PDF carrying a raster of `text` and no text layer."""
    import pymupdf

    typed = pymupdf.open()
    page = typed.new_page()
    if fontfile:
        page.insert_text((60, 120), text, fontsize=28, fontfile=fontfile)
    else:
        page.insert_text((60, 120), text, fontsize=28)
    # Rasterise, then rebuild a PDF from the raster alone — this is what makes
    # it "scanned": the glyphs survive as pixels, the text layer does not.
    pixmap = page.get_pixmap(dpi=200)
    typed.close()

    scanned = pymupdf.open()
    scanned_page = scanned.new_page(width=pixmap.width, height=pixmap.height)
    scanned_page.insert_image(scanned_page.rect, pixmap=pixmap)
    return scanned.tobytes()


def main() -> int:
    import pymupdf

    print("tesseract via PyMuPDF")
    try:
        tessdata = pymupdf.get_tessdata()
        print(f"  ✓ get_tessdata() -> {tessdata}")
    except Exception as exc:
        print(f"  ✗ get_tessdata() failed: {exc}")
        return 1

    from deeptutor.reading.ocr import _ocr_language

    language = _ocr_language()
    print(f"  ✓ language spec  -> {language}")

    # A Thai-capable font, if this image ships one. Without it the probe still
    # proves the pipeline, just not the Thai glyph shaping.
    import glob

    thai_font = next(
        iter(
            glob.glob("/usr/share/fonts/**/NotoSansThai*.ttf", recursive=True)
            or glob.glob("/usr/share/fonts/**/*Thai*.ttf", recursive=True)
        ),
        None,
    )

    cases = [("english", "Immersive reading OCR probe 12345", None)]
    if thai_font:
        cases.append(("thai", "ทดสอบการอ่านเอกสารสแกน", thai_font))
    else:
        print("  ! no Thai font in this image — skipping the Thai render")

    failures = 0
    for name, text, font in cases:
        print(f"\n{name}: {text!r}")
        pdf = _image_only_pdf(text, font)

        doc = pymupdf.open("pdf", pdf)
        residual = "".join(page.get_text() for page in doc).strip()
        doc.close()
        if residual:
            print(f"  ✗ not actually scanned — a text layer survived: {residual[:60]!r}")
            failures += 1
            continue
        print("  ✓ no text layer (a real scanned-PDF shape)")

        doc = pymupdf.open("pdf", pdf)
        try:
            ocr_pdf = doc[0].get_pixmap(dpi=300).pdfocr_tobytes(
                language=language, tessdata=tessdata
            )
        except Exception as exc:
            print(f"  ✗ OCR raised: {exc}")
            failures += 1
            continue
        finally:
            doc.close()

        out = pymupdf.open("pdf", ocr_pdf)
        recovered = "".join(page.get_text() for page in out).strip()
        out.close()
        if recovered:
            print(f"  ✓ recovered: {recovered[:80]!r}")
        else:
            print("  ✗ OCR produced no text")
            failures += 1

    print("\n" + ("ALL PASS" if not failures else f"{failures} FAILED"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
