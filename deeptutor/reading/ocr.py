"""Recover a document whose text is only a picture, by OCR, without losing its grid.

Two shapes of the same problem reach
:func:`deeptutor.reading.extract.extract_material` looking like an empty file:

* a **scanned PDF** — PyMuPDF returns "" for every page because there is
  nothing on it but an image;
* a **picture-only deck** — a PPTX exported from a design tool, where each
  slide is one full-bleed image and the OOXML carries no text run at all.

Rejecting either is honest but useless — the material the user actually wants
to read is right there, one OCR pass away.

Two things make this more than "run OCR and hand back a string":

* **The grid is the locator space.** A PDF is the one format the reader
  renders faithfully, so ``locator == physical page number`` and an annotation
  is stored normalised against that page's box; for a deck ``locator == slide
  number``. Any recovery that returns flat markdown would put unit 7 on page 3
  and land every highlight in the wrong place. Every provider here therefore
  emits *exactly* one unit per page/slide, in order, or declines.
* **Selection happens in the browser, not here.** The reader builds its
  selection surface from pdf.js ``getTextContent()`` (``PdfPage.tsx``), so text
  we only know server-side would leave the reader's core gesture — select,
  highlight, ask — dead on precisely these documents. The Tesseract provider
  therefore returns a rebuilt PDF carrying an invisible OCR text layer, which
  the store writes in place of the original bytes.

Provider order is deliberate: an operator who has configured a heavyweight
parse engine (MinerU, Docling) has already told us which OCR they want, and
those engines read Thai layout better than Tesseract does. Everything else
falls back to PyMuPDF's built-in Tesseract binding, which costs no extra Python
dependency because PyMuPDF is already core.

Configuration is environment-only and deliberately so: this path runs *only*
for a document that would otherwise be rejected outright, so there is no
default to protect and nothing to tune for the common case.

* ``DEEPTUTOR_READING_OCR`` — set falsey to refuse OCR entirely.
* ``DEEPTUTOR_READING_OCR_LANGUAGE`` — Tesseract language spec ("tha+eng").
  Defaults to the interface language plus English.
* ``DEEPTUTOR_READING_OCR_DPI`` — render resolution, default 300.
* ``DEEPTUTOR_READING_OCR_MAX_SECONDS`` — wall-clock budget, default 300.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import time
from typing import Any

from deeptutor.reading.models import ReadingError

logger = logging.getLogger(__name__)

# 300 dpi is the resolution Tesseract's models were trained around; 150 loses
# Thai tone marks and 600 costs four times the pixels for no accuracy gain.
DEFAULT_OCR_DPI = 300
# A synchronous upload is holding a worker thread for the whole pass, so the
# budget bounds what the caller waits for rather than how much we attempt.
DEFAULT_OCR_BUDGET_SECONDS = 300.0
# Rendered width, in pixels, to hand Tesseract for an embedded slide image.
# An image has no meaningful dpi of its own, so the PDF path's 300 dpi has no
# equivalent here; this is the pixel width that A4-at-300-dpi works out to, and
# small text OCRs better upscaled than at its native size.
SLIDE_OCR_TARGET_WIDTH = 2400

# Interface language -> Tesseract traineddata name. English is always appended:
# scans mix in English headers, numbers and stamps far more often than not.
_TESSERACT_LANGUAGES = {
    "th": "tha",
    "en": "eng",
    "zh": "chi_sim",
    "ja": "jpn",
    "ko": "kor",
    "de": "deu",
    "fr": "fra",
    "es": "spa",
    "pt": "por",
    "ru": "rus",
    "vi": "vie",
    "id": "ind",
    "ar": "ara",
    "hi": "hin",
}

# OOXML namespaces, for reading a deck's slide order and picture references.
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# Engines whose output we trust to be a real OCR of an image-only page. The
# others in the registry read an existing text layer and would return the same
# nothing PyMuPDF already did.
_OCR_CAPABLE_ENGINES = frozenset({"mineru", "docling"})

# MinerU/Docling block types that carry reader-facing prose. Layout furniture
# (headers, footers, page numbers) is dropped for the same reason the RAG block
# policy drops it: it is not what the page says.
_SKIPPED_BLOCK_TYPES = frozenset({"footer", "header", "page_number", "page_footer", "page_header"})

# Both Tesseract providers raise this, so it lives in one place.
_NO_ENGINE_GUIDANCE = (
    "No OCR engine is available. Install Tesseract with the language packs you "
    "need (macOS: `brew install tesseract tesseract-lang`, Debian/Ubuntu: "
    "`apt install tesseract-ocr tesseract-ocr-tha`), or select MinerU/Docling "
    "in Settings → Document Parsing."
)


@dataclass(frozen=True, slots=True)
class OcrResult:
    """What a successful recovery hands back to the extractor."""

    units: tuple[str, ...]
    engine: str
    # A rebuilt PDF carrying an invisible text layer, when the provider can
    # produce one. The store writes it in place of the uploaded bytes so the
    # browser gets a selection surface; None means keep the original file.
    searchable_pdf: bytes | None = None


def recover_with_ocr(source: Path, page_count: int) -> OcrResult:
    """OCR *source* into one text unit per physical page.

    ``units`` always has exactly ``page_count`` entries so the caller's locator
    space is untouched. Raises :class:`ReadingError` — carrying the
    operator-facing fix — when no provider can run.
    """
    if not _ocr_enabled():
        raise _unavailable(source, "OCR is disabled (DEEPTUTOR_READING_OCR).")
    if page_count <= 0:
        raise _unavailable(source, "The PDF has no pages to OCR.")

    from_engine = _pages_from_parse_service(source, page_count)
    if from_engine is not None:
        return from_engine

    return _pages_from_tesseract(source, page_count)


# ---------------------------------------------------------------------------
# Provider 1 — the configured parse engine (MinerU / Docling)
# ---------------------------------------------------------------------------


def _pages_from_parse_service(source: Path, page_count: int) -> OcrResult | None:
    """Use the operator's configured engine, or return None to fall through.

    Declines — rather than raises — on every failure. A misconfigured heavy
    engine must not cost the user the Tesseract path that would have worked.
    """
    try:
        from deeptutor.services.parsing import get_parse_service
    except ImportError:  # pragma: no cover - parse layer is part of the package
        return None

    service = get_parse_service()
    try:
        engine = service.active_engine()
    except Exception:
        logger.debug("Could not resolve the active parse engine", exc_info=True)
        return None

    if engine not in _OCR_CAPABLE_ENGINES:
        return None

    try:
        parsed = service.parse(source, engine=engine)
    except Exception as exc:
        logger.info("OCR via the '%s' engine failed (%s) — falling back", engine, exc)
        return None

    blocks = parsed.blocks
    if not blocks:
        # Markdown alone cannot be mapped back onto physical pages, and a
        # mis-mapped unit is worse than no unit: it would silently misplace
        # every annotation the reader records against it.
        logger.info("The '%s' engine returned no page-addressable blocks", engine)
        return None

    units = _pages_from_blocks(blocks, page_count)
    if not any(unit.strip() for unit in units):
        return None
    logger.info("Recovered %s via OCR (engine=%s)", source.name, engine)
    return OcrResult(units=units, engine=engine)


def _pages_from_blocks(blocks: list[dict[str, Any]], page_count: int) -> tuple[str, ...]:
    """Group parser blocks into per-page text, keyed by their ``page_idx``.

    Blocks outside the known page range are dropped rather than clamped onto
    the nearest page — the same rule ``_pdf_outline`` applies to stale
    bookmarks, and for the same reason.
    """
    pages: list[list[str]] = [[] for _ in range(page_count)]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "") in _SKIPPED_BLOCK_TYPES:
            continue
        index = block.get("page_idx")
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        if not 0 <= index < page_count:
            continue
        text = _block_text(block)
        if text:
            pages[index].append(text)
    return tuple("\n\n".join(parts) for parts in pages)


def _block_text(block: dict[str, Any]) -> str:
    """The prose a block contributes, across the engines' differing key names."""
    for key in ("text", "content", "body", "code_body", "table_body"):
        value = block.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    caption = block.get("img_caption") or block.get("table_caption")
    if isinstance(caption, list):
        joined = " ".join(str(part).strip() for part in caption if str(part).strip())
        if joined:
            return joined
    elif isinstance(caption, str) and caption.strip():
        return caption.strip()
    return ""


# ---------------------------------------------------------------------------
# Provider 2 — PyMuPDF's built-in Tesseract binding
# ---------------------------------------------------------------------------


def _pages_from_tesseract(source: Path, page_count: int) -> OcrResult:
    """Render each page, OCR it, and rebuild the PDF around the text layer.

    One pass yields both halves of what the reader needs: ``pdfocr_tobytes``
    writes an invisible text layer under the page image, and reading that page
    back gives the unit text. Doing it as two passes would OCR everything
    twice for the same result.
    """
    import pymupdf

    language = _ocr_language()
    dpi = _ocr_dpi()
    try:
        tessdata = pymupdf.get_tessdata()
    except Exception as exc:
        raise _unavailable(source, _NO_ENGINE_GUIDANCE) from exc

    deadline = time.monotonic() + _ocr_budget_seconds()
    logger.info(
        "OCR fallback for %s: %s page(s), language=%s, dpi=%s",
        source.name,
        page_count,
        language,
        dpi,
    )

    try:
        with pymupdf.open(source) as doc, pymupdf.open() as rebuilt:
            for number, page in enumerate(doc, start=1):
                if time.monotonic() > deadline:
                    raise _unavailable(
                        source,
                        f"OCR ran out of time after {number - 1} of {page_count} pages. "
                        "Raise DEEPTUTOR_READING_OCR_MAX_SECONDS, or OCR the file "
                        "before uploading it.",
                    )
                pixmap = page.get_pixmap(dpi=dpi)
                try:
                    ocr_bytes = pixmap.pdfocr_tobytes(language=language, tessdata=tessdata)
                finally:
                    # Release the page bitmap before rendering the next one;
                    # an A4 page at 300 dpi is ~26 MB of RGB.
                    del pixmap
                with pymupdf.open(stream=ocr_bytes, filetype="pdf") as ocr_page:
                    rebuilt.insert_pdf(ocr_page)
            units = tuple((page.get_text() or "") for page in rebuilt)
            searchable = rebuilt.tobytes(garbage=3, deflate=True)
    except ReadingError:
        raise
    except Exception as exc:
        raise _unavailable(
            source,
            f"OCR failed ({exc}). Check that Tesseract has the '{language}' "
            "language data installed.",
        ) from exc

    if not any(unit.strip() for unit in units):
        raise _unavailable(
            source,
            f"OCR produced no text for the '{language}' language. Try setting "
            "DEEPTUTOR_READING_OCR_LANGUAGE to the document's actual language.",
        )
    logger.info("Recovered %s via OCR (engine=tesseract)", source.name)
    return OcrResult(units=units, engine="tesseract", searchable_pdf=searchable)


# ---------------------------------------------------------------------------
# Slide decks whose slides are pictures
# ---------------------------------------------------------------------------


def recover_slides_with_ocr(source: Path) -> OcrResult:
    """OCR a picture-only deck into one text unit per slide.

    Unlike the PDF path there is nothing to render: the pictures are already
    in the file. Reading them straight out of the OOXML package keeps this
    dependency-free — rendering slides would need LibreOffice on the host, for
    a deck whose every slide is a single image anyway.
    """
    if not _ocr_enabled():
        raise _unavailable(source, "OCR is disabled (DEEPTUTOR_READING_OCR).")

    try:
        slides = _pptx_slide_images(source)
    except Exception as exc:
        raise _unavailable(source, f"The slide package could not be read ({exc}).") from exc

    if not slides:
        raise _unavailable(source, "The deck has no slides to OCR.")
    if not any(slides):
        raise _unavailable(
            source,
            "The slides carry neither text nor pictures, so there is nothing to read.",
        )

    from_engine = _pages_from_parse_service(source, len(slides))
    if from_engine is not None:
        return from_engine

    return _slides_from_tesseract(source, slides)


def _slides_from_tesseract(source: Path, slides: list[list[bytes]]) -> OcrResult:
    """OCR every picture on every slide, in the order they are drawn."""
    import pymupdf

    language = _ocr_language()
    try:
        tessdata = pymupdf.get_tessdata()
    except Exception as exc:
        raise _unavailable(source, _NO_ENGINE_GUIDANCE) from exc

    deadline = time.monotonic() + _ocr_budget_seconds()
    logger.info("OCR fallback for %s: %s slide(s), language=%s", source.name, len(slides), language)

    units: list[str] = []
    for number, images in enumerate(slides, start=1):
        if time.monotonic() > deadline:
            raise _unavailable(
                source,
                f"OCR ran out of time after {number - 1} of {len(slides)} slides. "
                "Raise DEEPTUTOR_READING_OCR_MAX_SECONDS, or OCR the file "
                "before uploading it.",
            )
        parts: list[str] = []
        for image in images:
            text = _ocr_image(image, language=language, tessdata=tessdata)
            if text:
                parts.append(text)
        units.append("\n\n".join(parts))

    if not any(unit.strip() for unit in units):
        raise _unavailable(
            source,
            f"OCR produced no text for the '{language}' language. Try setting "
            "DEEPTUTOR_READING_OCR_LANGUAGE to the deck's actual language.",
        )
    logger.info("Recovered %s via OCR (engine=tesseract)", source.name)
    return OcrResult(units=tuple(units), engine="tesseract")


def _ocr_image(data: bytes, *, language: str, tessdata: str) -> str:
    """OCR one embedded picture, upscaled to something Tesseract reads well."""
    import pymupdf

    try:
        with pymupdf.open(stream=data) as image:
            page = image[0]
            # get_pixmap renders the image's *declared* size at 72 dpi, which for
            # a slide picture is usually well below its own pixel count. Scale to
            # a fixed target width instead of trusting either number.
            width = max(page.rect.width, 1.0)
            zoom = min(max(SLIDE_OCR_TARGET_WIDTH / width, 1.0), 6.0)
            # alpha=False because PDFOCR refuses to write an alpha channel, and a
            # PNG exported from a design tool almost always carries one.
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        ocr_bytes = pixmap.pdfocr_tobytes(language=language, tessdata=tessdata)
        with pymupdf.open(stream=ocr_bytes, filetype="pdf") as ocr_page:
            return (ocr_page[0].get_text() or "").strip()
    except Exception:
        # One unreadable picture must not lose the rest of the deck.
        logger.debug("Could not OCR an embedded picture", exc_info=True)
        return ""


def _pptx_slide_images(source: Path) -> list[list[bytes]]:
    """Every picture on every slide, slides in presentation order.

    Presentation order comes from ``sldIdLst`` rather than the ``slideN.xml``
    file names: the numbers are creation order, and a deck whose slides were
    reordered would otherwise attribute each slide's text to the wrong locator
    — the same misalignment the PDF path refuses to risk.
    """
    import xml.etree.ElementTree as ET
    import zipfile

    with zipfile.ZipFile(source) as package:
        names = set(package.namelist())
        out: list[list[bytes]] = []
        for member in _pptx_slide_order(package, names):
            rels = _ooxml_rels(package, member, names)
            images: list[bytes] = []
            try:
                root = ET.fromstring(package.read(member))
            except ET.ParseError:
                out.append([])
                continue
            # Document order of <a:blip r:embed> is the order the pictures are
            # drawn, which is the order a reader would meet them.
            for blip in root.iter(f"{{{_A_NS}}}blip"):
                target = rels.get(blip.get(f"{{{_R_NS}}}embed") or "")
                if target and target in names:
                    images.append(package.read(target))
            out.append(images)
    return out


def _pptx_slide_order(package, names: set[str]) -> list[str]:
    """Slide parts in presentation order, falling back to natural file order."""
    import re
    import xml.etree.ElementTree as ET

    presentation = "ppt/presentation.xml"
    if presentation in names:
        rels = _ooxml_rels(package, presentation, names)
        try:
            root = ET.fromstring(package.read(presentation))
            ordered = [
                rels.get(node.get(f"{{{_R_NS}}}id") or "")
                for node in root.iter(f"{{{_P_NS}}}sldId")
            ]
            ordered = [name for name in ordered if name and name in names]
            if ordered:
                return ordered
        except ET.ParseError:
            logger.debug("Unreadable presentation.xml; using file order", exc_info=True)

    return sorted(
        (name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
        key=lambda name: int(re.search(r"(\d+)\.xml$", name).group(1)),
    )


def _ooxml_rels(package, member: str, names: set[str]) -> dict[str, str]:
    """Relationship id -> package part, for one OOXML part."""
    import posixpath
    import xml.etree.ElementTree as ET

    folder, _, filename = member.rpartition("/")
    rels_name = f"{folder}/_rels/{filename}.rels"
    if rels_name not in names:
        return {}
    try:
        root = ET.fromstring(package.read(rels_name))
    except ET.ParseError:
        return {}

    mapping: dict[str, str] = {}
    for node in root.iter(f"{{{_PKG_REL_NS}}}Relationship"):
        rel_id, target = node.get("Id"), node.get("Target")
        if not rel_id or not target or "://" in target:
            continue
        mapping[rel_id] = posixpath.normpath(posixpath.join(folder, target))
    return mapping


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _ocr_enabled() -> bool:
    raw = os.getenv("DEEPTUTOR_READING_OCR", "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _ocr_language() -> str:
    """The Tesseract language spec: explicit override, else UI language + eng."""
    override = os.getenv("DEEPTUTOR_READING_OCR_LANGUAGE", "").strip()
    if override:
        return override

    code = "en"
    try:
        from deeptutor.services.config import parse_language
        from deeptutor.services.config.loader import load_config_with_main

        config = load_config_with_main("main.yaml")
        code = parse_language((config.get("system") or {}).get("language"))
    except Exception:
        logger.debug("Falling back to English OCR: interface language unreadable", exc_info=True)

    primary = _TESSERACT_LANGUAGES.get(code, "eng")
    return primary if primary == "eng" else f"{primary}+eng"


def _ocr_dpi() -> int:
    return _positive_env("DEEPTUTOR_READING_OCR_DPI", DEFAULT_OCR_DPI, lo=72, hi=600)


def _ocr_budget_seconds() -> float:
    return float(
        _positive_env(
            "DEEPTUTOR_READING_OCR_MAX_SECONDS",
            int(DEFAULT_OCR_BUDGET_SECONDS),
            lo=10,
            hi=86_400,
        )
    )


def _positive_env(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(lo, min(hi, int(float(raw))))
    except ValueError:
        logger.warning("Ignoring %s=%r: not a number", name, raw)
        return default


def _unavailable(source: Path, guidance: str) -> ReadingError:
    """The rejection the reader shows, with the fix appended.

    Keeps the original two sentences verbatim: they are what the UI, the API
    contract tests and existing user reports all say.
    """
    return ReadingError(
        f"{source.name}: no readable text could be extracted. "
        f"A scanned document needs OCR before it can be read here. {guidance}"
    )


__all__ = [
    "DEFAULT_OCR_BUDGET_SECONDS",
    "DEFAULT_OCR_DPI",
    "SLIDE_OCR_TARGET_WIDTH",
    "OcrResult",
    "recover_slides_with_ocr",
    "recover_with_ocr",
]
