"""Tests for the OCR fallback that rescues PDFs with no text layer.

The Tesseract binary is not assumed: everything about *routing* and *page
alignment* is exercised with stubs, and only the one end-to-end test that needs
a real OCR engine is skipped when Tesseract is absent.
"""

from __future__ import annotations

import io
from pathlib import Path
import zipfile

import pytest

from deeptutor.reading import extract as extract_module
from deeptutor.reading.extract import extract_material
from deeptutor.reading.models import ReadingError
from deeptutor.reading.ocr import (
    OcrResult,
    _ooxml_rels,
    _pages_from_blocks,
    _pptx_slide_images,
    _pptx_slide_order,
    recover_slides_with_ocr,
    recover_with_ocr,
)

pymupdf = pytest.importorskip("pymupdf")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _scanned_pdf(path: Path, pages: int = 2) -> Path:
    """A PDF whose pages carry a picture and no text at all."""
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40))
        pixmap.set_rect(pixmap.irect, (255, 255, 255))
        page.insert_image(pymupdf.Rect(10, 10, 50, 50), pixmap=pixmap)
    doc.save(path)
    doc.close()
    return path


class _StubService:
    """Stands in for ParseService with a fixed engine and parse result."""

    def __init__(self, engine: str, parsed: object | Exception | None = None) -> None:
        self._engine = engine
        self._parsed = parsed
        self.calls: list[str] = []

    def active_engine(self) -> str:
        return self._engine

    def parse(self, source, *, engine=None):
        self.calls.append(str(source))
        if isinstance(self._parsed, Exception):
            raise self._parsed
        return self._parsed


class _Parsed:
    def __init__(self, blocks=None, markdown: str = "") -> None:
        self.blocks = blocks
        self.markdown = markdown


@pytest.fixture
def stub_parse_service(monkeypatch):
    """Install a fake ParseService and return a setter for it."""

    def install(service) -> None:
        import deeptutor.services.parsing as parsing

        monkeypatch.setattr(parsing, "get_parse_service", lambda: service)

    return install


# ---------------------------------------------------------------------------
# page alignment — the property the whole locator space rests on
# ---------------------------------------------------------------------------


def test_blocks_land_on_the_page_their_index_names() -> None:
    blocks = [
        {"type": "text", "text": "first page", "page_idx": 0},
        {"type": "text", "text": "third page", "page_idx": 2},
    ]

    units = _pages_from_blocks(blocks, 3)

    assert units == ("first page", "", "third page")


def test_every_page_gets_a_unit_even_when_ocr_found_nothing_on_it() -> None:
    units = _pages_from_blocks([{"type": "text", "text": "only", "page_idx": 1}], 4)

    assert len(units) == 4


def test_blocks_outside_the_page_range_are_dropped_not_clamped() -> None:
    blocks = [
        {"type": "text", "text": "real", "page_idx": 0},
        {"type": "text", "text": "stale bookmark", "page_idx": 9},
        {"type": "text", "text": "negative", "page_idx": -1},
    ]

    assert _pages_from_blocks(blocks, 2) == ("real", "")


def test_layout_furniture_does_not_become_reading_text() -> None:
    blocks = [
        {"type": "page_header", "text": "CONFIDENTIAL", "page_idx": 0},
        {"type": "text", "text": "the body", "page_idx": 0},
        {"type": "page_number", "text": "1", "page_idx": 0},
        {"type": "footer", "text": "printed 2026", "page_idx": 0},
    ]

    assert _pages_from_blocks(blocks, 1) == ("the body",)


def test_block_text_reads_the_other_engines_key_names() -> None:
    blocks = [
        {"type": "table", "table_body": "| a | b |", "page_idx": 0},
        {"type": "image", "img_caption": ["Figure 1", "the diagram"], "page_idx": 1},
        {"type": "code", "code_body": "print(1)", "page_idx": 2},
    ]

    assert _pages_from_blocks(blocks, 3) == ("| a | b |", "Figure 1 the diagram", "print(1)")


def test_a_non_integer_page_index_is_ignored() -> None:
    blocks = [
        {"type": "text", "text": "keep", "page_idx": 0},
        {"type": "text", "text": "bool is not a page", "page_idx": True},
        {"type": "text", "text": "string is not a page", "page_idx": "1"},
        "not even a block",
    ]

    assert _pages_from_blocks(blocks, 2) == ("keep", "")


# ---------------------------------------------------------------------------
# provider routing
# ---------------------------------------------------------------------------


def test_a_configured_ocr_engine_is_used_before_tesseract(
    tmp_path: Path, stub_parse_service
) -> None:
    source = _scanned_pdf(tmp_path / "scan.pdf")
    service = _StubService(
        "mineru", _Parsed(blocks=[{"type": "text", "text": "จากมิเนอรู", "page_idx": 0}])
    )
    stub_parse_service(service)

    result = recover_with_ocr(source, 2)

    assert result.engine == "mineru"
    assert result.units == ("จากมิเนอรู", "")
    assert result.searchable_pdf is None
    assert service.calls == [str(source)]


def test_an_engine_that_only_reads_text_layers_is_skipped(
    tmp_path: Path, stub_parse_service
) -> None:
    source = _scanned_pdf(tmp_path / "scan.pdf")
    service = _StubService("text_only", _Parsed(markdown="whatever"))
    stub_parse_service(service)

    with pytest.raises(ReadingError):
        recover_with_ocr(source, 2)

    assert service.calls == []  # never asked to parse


def test_markdown_without_blocks_is_refused_rather_than_mis_paged(
    tmp_path: Path, stub_parse_service
) -> None:
    """Flat markdown cannot be mapped to pages, and a wrong page is worse."""
    source = _scanned_pdf(tmp_path / "scan.pdf")
    stub_parse_service(_StubService("docling", _Parsed(markdown="page one\n\npage two")))

    with pytest.raises(ReadingError):
        recover_with_ocr(source, 2)


def test_a_failing_engine_falls_through_instead_of_blocking_the_upload(
    tmp_path: Path, stub_parse_service
) -> None:
    source = _scanned_pdf(tmp_path / "scan.pdf")
    stub_parse_service(_StubService("mineru", RuntimeError("models not downloaded")))

    # Falls through to Tesseract, which then reports its own situation. Either
    # way the caller learns what to fix, and never sees the engine's traceback.
    with pytest.raises(ReadingError) as excinfo:
        recover_with_ocr(source, 2)

    assert "models not downloaded" not in str(excinfo.value)


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------


def test_ocr_can_be_switched_off_entirely(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_READING_OCR", "0")
    source = _scanned_pdf(tmp_path / "scan.pdf")

    with pytest.raises(ReadingError) as excinfo:
        recover_with_ocr(source, 1)

    assert "DEEPTUTOR_READING_OCR" in str(excinfo.value)


def test_the_language_override_wins(monkeypatch) -> None:
    from deeptutor.reading import ocr

    monkeypatch.setenv("DEEPTUTOR_READING_OCR_LANGUAGE", "tha")

    assert ocr._ocr_language() == "tha"


def test_the_interface_language_picks_the_traineddata(monkeypatch) -> None:
    from deeptutor.reading import ocr

    monkeypatch.delenv("DEEPTUTOR_READING_OCR_LANGUAGE", raising=False)
    monkeypatch.setattr(
        "deeptutor.services.config.loader.load_config_with_main",
        lambda _name: {"system": {"language": "th"}},
    )

    assert ocr._ocr_language() == "tha+eng"


def test_english_does_not_get_a_redundant_second_pass(monkeypatch) -> None:
    from deeptutor.reading import ocr

    monkeypatch.delenv("DEEPTUTOR_READING_OCR_LANGUAGE", raising=False)
    monkeypatch.setattr(
        "deeptutor.services.config.loader.load_config_with_main",
        lambda _name: {"system": {"language": "en"}},
    )

    assert ocr._ocr_language() == "eng"


def test_a_nonsense_dpi_falls_back_to_the_default(monkeypatch) -> None:
    from deeptutor.reading import ocr

    monkeypatch.setenv("DEEPTUTOR_READING_OCR_DPI", "not-a-number")

    assert ocr._ocr_dpi() == ocr.DEFAULT_OCR_DPI


def test_dpi_is_clamped_to_something_tesseract_can_use(monkeypatch) -> None:
    from deeptutor.reading import ocr

    monkeypatch.setenv("DEEPTUTOR_READING_OCR_DPI", "5000")

    assert ocr._ocr_dpi() == 600


# ---------------------------------------------------------------------------
# extract_material integration
# ---------------------------------------------------------------------------


def test_a_scanned_pdf_keeps_its_page_grid_after_recovery(tmp_path: Path, monkeypatch) -> None:
    source = _scanned_pdf(tmp_path / "scan.pdf", pages=3)
    monkeypatch.setattr(
        "deeptutor.reading.ocr.recover_with_ocr",
        lambda path, count: OcrResult(
            units=tuple(f"หน้า {n}" for n in range(1, count + 1)),
            engine="tesseract",
            searchable_pdf=b"%PDF-1.7 rebuilt",
        ),
    )

    extraction = extract_material(source)

    assert extraction.units == ("หน้า 1", "หน้า 2", "หน้า 3")
    assert extraction.unit == "page"
    assert extraction.render_mode == "pdf"
    assert extraction.has_raw_view is True
    assert extraction.extractor == "pymupdf+ocr:tesseract"
    assert extraction.raw_bytes == b"%PDF-1.7 rebuilt"


def test_a_pdf_that_already_has_text_never_reaches_ocr(tmp_path: Path, monkeypatch) -> None:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "already readable")
    doc.save(tmp_path / "text.pdf")
    doc.close()

    def _explode(*_args, **_kwargs):
        raise AssertionError("OCR must not run for a PDF with a text layer")

    monkeypatch.setattr("deeptutor.reading.ocr.recover_with_ocr", _explode)

    assert "already readable" in extract_material(tmp_path / "text.pdf").units[0]


def test_a_non_pdf_with_no_text_is_never_sent_to_ocr(tmp_path: Path, monkeypatch) -> None:
    """OCR rebuilds PDF pages; there is nothing for it to do to a .txt."""
    from deeptutor.reading.extract import Extraction

    empty = tmp_path / "blank.txt"
    empty.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(
        extract_module,
        "_extract_sections",
        lambda _source: Extraction(units=("",), unit="section", extractor="text"),
    )

    def _explode(*_args, **_kwargs):
        raise AssertionError("OCR must not run for a non-PDF")

    monkeypatch.setattr("deeptutor.reading.ocr.recover_with_ocr", _explode)

    with pytest.raises(ReadingError) as excinfo:
        extract_material(empty)

    message = str(excinfo.value)
    assert "no readable text" in message
    assert "OCR" in message


def test_the_rejection_still_names_ocr_when_no_provider_can_run(tmp_path: Path) -> None:
    """The API contract (and the UI copy) depend on these two sentences."""
    source = _scanned_pdf(tmp_path / "scan.pdf")

    with pytest.raises(ReadingError) as excinfo:
        recover_with_ocr(source, 2)

    message = str(excinfo.value)
    assert "no readable text could be extracted" in message
    assert "A scanned document needs OCR before it can be read here." in message


# ---------------------------------------------------------------------------
# the real thing — only where Tesseract is installed
# ---------------------------------------------------------------------------


def _tesseract_available() -> bool:
    try:
        pymupdf.get_tessdata()
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _tesseract_available(), reason="Tesseract is not installed")
def test_a_real_scan_round_trips_into_selectable_text(tmp_path: Path, monkeypatch) -> None:
    """Render text to an image-only PDF, then read it back through OCR."""
    monkeypatch.setenv("DEEPTUTOR_READING_OCR_LANGUAGE", "eng")

    typed = pymupdf.open()
    page = typed.new_page()
    page.insert_text((72, 200), "READING ENGINE", fontsize=36)
    flattened = pymupdf.open()
    pixmap = page.get_pixmap(dpi=200)
    image_page = flattened.new_page(width=page.rect.width, height=page.rect.height)
    image_page.insert_image(image_page.rect, pixmap=pixmap)
    source = tmp_path / "scan.pdf"
    flattened.save(source)
    typed.close()
    flattened.close()

    extraction = extract_material(source)

    assert "READING" in extraction.units[0].upper()
    assert extraction.raw_bytes is not None
    # The rebuilt file is what the browser gets, and it must be selectable.
    with pymupdf.open(stream=extraction.raw_bytes, filetype="pdf") as rebuilt:
        assert len(rebuilt) == 1
        assert "READING" in (rebuilt[0].get_text() or "").upper()


# ---------------------------------------------------------------------------
# slide decks whose slides are pictures
# ---------------------------------------------------------------------------

_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _picture_bytes(label: str = "") -> bytes:
    """A small PNG, optionally with text drawn on it for a live OCR run."""
    doc = pymupdf.open()
    page = doc.new_page(width=520, height=300)
    if label:
        page.insert_text((40, 160), label, fontsize=44)
    pixmap = page.get_pixmap(dpi=150)
    doc.close()
    return pixmap.tobytes("png")


def _picture_deck(path: Path, labels: list[str]) -> Path:
    """A real PPTX where every slide is one picture and no slide has text."""
    pptx = pytest.importorskip("pptx")
    from pptx.util import Emu

    presentation = pptx.Presentation()
    blank = presentation.slide_layouts[6]
    for label in labels:
        slide = presentation.slides.add_slide(blank)
        slide.shapes.add_picture(
            io.BytesIO(_picture_bytes(label)),
            Emu(0),
            Emu(0),
            width=presentation.slide_width,
            height=presentation.slide_height,
        )
    presentation.save(path)
    return path


def _synthetic_package(path: Path, *, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as package:
        for name, body in members.items():
            package.writestr(name, body)
    return path


def _rels(*pairs: tuple[str, str]) -> str:
    entries = "".join(
        f'<Relationship Id="{rid}" Target="{target}" Type="t"/>' for rid, target in pairs
    )
    return (
        '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
        f'package/2006/relationships">{entries}</Relationships>'
    )


def test_slide_order_follows_the_presentation_not_the_file_names(tmp_path: Path) -> None:
    """slideN.xml numbers are creation order; a reordered deck must not shift."""
    package = _synthetic_package(
        tmp_path / "deck.pptx",
        members={
            "ppt/presentation.xml": (
                f'<?xml version="1.0"?><p:presentation xmlns:p="{_P_NS}" xmlns:r="{_R_NS}">'
                '<p:sldIdLst><p:sldId r:id="rId2"/><p:sldId r:id="rId1"/></p:sldIdLst>'
                "</p:presentation>"
            ),
            "ppt/_rels/presentation.xml.rels": _rels(
                ("rId1", "slides/slide1.xml"), ("rId2", "slides/slide2.xml")
            ),
            "ppt/slides/slide1.xml": "<x/>",
            "ppt/slides/slide2.xml": "<x/>",
        },
    )

    with zipfile.ZipFile(package) as opened:
        order = _pptx_slide_order(opened, set(opened.namelist()))

    assert order == ["ppt/slides/slide2.xml", "ppt/slides/slide1.xml"]


def test_slide_order_falls_back_to_numeric_file_order(tmp_path: Path) -> None:
    """Without a readable presentation.xml, slide10 must still follow slide9."""
    package = _synthetic_package(
        tmp_path / "deck.pptx",
        members={f"ppt/slides/slide{n}.xml": "<x/>" for n in (1, 2, 9, 10, 11)},
    )

    with zipfile.ZipFile(package) as opened:
        order = _pptx_slide_order(opened, set(opened.namelist()))

    assert order == [f"ppt/slides/slide{n}.xml" for n in (1, 2, 9, 10, 11)]


def test_external_relationship_targets_are_not_followed(tmp_path: Path) -> None:
    """A rel pointing off the package is a link, not a part we can read."""
    package = _synthetic_package(
        tmp_path / "deck.pptx",
        members={
            "ppt/slides/slide1.xml": "<x/>",
            "ppt/slides/_rels/slide1.xml.rels": _rels(
                ("rId1", "../media/image1.png"), ("rId2", "https://example.com/x.png")
            ),
        },
    )

    with zipfile.ZipFile(package) as opened:
        mapping = _ooxml_rels(opened, "ppt/slides/slide1.xml", set(opened.namelist()))

    assert mapping == {"rId1": "ppt/media/image1.png"}


def test_every_slide_yields_an_entry_even_with_no_picture(tmp_path: Path) -> None:
    package = _synthetic_package(
        tmp_path / "deck.pptx",
        members={"ppt/slides/slide1.xml": "<x/>", "ppt/slides/slide2.xml": "<x/>"},
    )

    assert _pptx_slide_images(package) == [[], []]


def test_pictures_are_read_out_of_a_real_deck(tmp_path: Path) -> None:
    deck = _picture_deck(tmp_path / "deck.pptx", ["", "", ""])

    slides = _pptx_slide_images(deck)

    assert len(slides) == 3
    assert all(len(images) == 1 for images in slides)
    assert all(images[0].startswith(b"\x89PNG") for images in slides)


def test_a_picture_only_deck_becomes_one_unit_per_slide(tmp_path: Path, monkeypatch) -> None:
    deck = _picture_deck(tmp_path / "deck.pptx", ["", "", ""])
    monkeypatch.setattr(
        "deeptutor.reading.ocr.recover_slides_with_ocr",
        lambda _path: OcrResult(units=("สไลด์ 1", "สไลด์ 2", "สไลด์ 3"), engine="tesseract"),
    )

    extraction = extract_material(deck)

    assert extraction.units == ("สไลด์ 1", "สไลด์ 2", "สไลด์ 3")
    assert extraction.unit == "slide"
    assert extraction.extractor == "pptx+ocr:tesseract"


def test_a_deck_that_has_text_never_reaches_ocr(tmp_path: Path, monkeypatch) -> None:
    pptx = pytest.importorskip("pptx")

    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "หัวข้อจริง"
    deck = tmp_path / "text.pptx"
    presentation.save(deck)

    def _explode(*_args, **_kwargs):
        raise AssertionError("OCR must not run for a deck that carries text")

    monkeypatch.setattr("deeptutor.reading.ocr.recover_slides_with_ocr", _explode)

    extraction = extract_material(deck)

    assert extraction.extractor == "pptx"
    assert "หัวข้อจริง" in extraction.units[0]


def test_a_broken_deck_reports_being_broken_not_needing_ocr(tmp_path: Path, monkeypatch) -> None:
    """Only "this holds no text" routes to OCR; a corrupt package must not."""
    deck = _synthetic_package(tmp_path / "broken.pptx", members={"not-a-deck.xml": "<x/>"})

    def _explode(*_args, **_kwargs):
        raise AssertionError("OCR must not run for a corrupt package")

    monkeypatch.setattr("deeptutor.reading.ocr.recover_slides_with_ocr", _explode)

    with pytest.raises(ReadingError) as excinfo:
        extract_material(deck)

    assert "needs OCR" not in str(excinfo.value)


def test_the_filename_is_not_repeated_in_an_extractor_error(tmp_path: Path) -> None:
    """It read "blank.txt: blank.txt: no extractable text" before."""
    empty = tmp_path / "blank.txt"
    empty.write_text("   \n\n  ", encoding="utf-8")

    with pytest.raises(ReadingError) as excinfo:
        extract_material(empty)

    assert str(excinfo.value).count("blank.txt") == 1


def test_ocr_can_be_switched_off_for_decks_too(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_READING_OCR", "0")
    deck = _picture_deck(tmp_path / "deck.pptx", [""])

    with pytest.raises(ReadingError) as excinfo:
        recover_slides_with_ocr(deck)

    assert "DEEPTUTOR_READING_OCR" in str(excinfo.value)


@pytest.mark.skipif(not _tesseract_available(), reason="Tesseract is not installed")
def test_a_real_picture_deck_round_trips_into_slide_text(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_READING_OCR_LANGUAGE", "eng")
    deck = _picture_deck(tmp_path / "deck.pptx", ["ALPHA", "BRAVO"])

    extraction = extract_material(deck)

    assert extraction.unit == "slide"
    assert len(extraction.units) == 2
    assert "ALPHA" in extraction.units[0].upper()
    assert "BRAVO" in extraction.units[1].upper()
