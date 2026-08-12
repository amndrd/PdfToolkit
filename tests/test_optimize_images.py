"""Compression, repair and image conversion — the optional-extra features."""

from __future__ import annotations

import pytest

from conftest import make_pdf, page_widths
from recto.core import images_to_pdf, optimize, pdf_to_images, repair
from recto.core.images import FORMATS, PAGE_SIZES
from recto.errors import InvalidDocument, UnsupportedOperation

pikepdf = pytest.importorskip("pikepdf", reason="requires the 'optimize' extra")
pypdfium2 = pytest.importorskip("pypdfium2", reason="requires the 'images' extra")
PIL = pytest.importorskip("PIL", reason="requires the 'images' extra")


class TestOptimize:
    def test_output_is_a_valid_pdf(self, sample10, out):
        optimize(sample10, out)
        assert page_widths(out) == list(range(200, 210))

    def test_lossless_by_default(self, sample10, out):
        result = optimize(sample10, out)
        assert result.details["lossless"] is True
        assert result.details["images_recompressed"] == 0

    def test_reports_the_saving(self, sample10, out):
        result = optimize(sample10, out)
        assert result.input_bytes > 0
        assert result.details["bytes_saved"] == result.input_bytes - result.output_bytes

    def test_linearize(self, sample10, out):
        result = optimize(sample10, out, linearize=True)
        assert result.details["linearized"] is True
        assert out.stat().st_size > 0

    def test_strip_metadata(self, tmp_path, out):
        source = make_pdf(tmp_path / "m.pdf", 2, metadata={"/Title": "Confidential"})
        optimize(source, out, strip_metadata=True)
        from recto.core import read_metadata

        assert read_metadata(out)["title"] is None

    def test_rejects_out_of_range_quality(self, sample, out):
        for quality in (0, 101, -5):
            with pytest.raises(InvalidDocument, match="between 1 and 100"):
                optimize(sample, out, image_quality=quality, overwrite=True)

    def test_max_dpi_requires_a_quality(self, sample, out):
        with pytest.raises(InvalidDocument, match="--image-quality"):
            optimize(sample, out, max_dpi=150)

    def test_image_quality_path_runs(self, sample, out):
        """No embedded images here, so nothing is re-encoded — but it must not fail."""
        result = optimize(sample, out, image_quality=75, max_dpi=150)
        assert result.details["images_recompressed"] == 0
        assert result.details["lossless"] is False

    def test_password_protected_input(self, locked, out):
        optimize(locked, out, password="s3cret")
        assert out.exists()

    def test_missing_password(self, locked, out):
        from recto.errors import PasswordRequired

        with pytest.raises(PasswordRequired):
            optimize(locked, out)


class TestRepair:
    def test_rebuilds_a_healthy_file(self, sample10, out):
        result = repair(sample10, out)
        assert result.pages == 10
        assert page_widths(out) == list(range(200, 210))

    def test_recovers_a_broken_xref(self, tmp_path, out):
        """Corrupt the cross-reference table; qpdf should reconstruct it."""
        source = make_pdf(tmp_path / "ok.pdf", 4)
        data = bytearray(source.read_bytes())
        marker = data.rfind(b"startxref")
        assert marker != -1
        # Point startxref at a bogus offset — the classic broken-download shape.
        end = data.find(b"%%EOF", marker)
        data[marker:end] = b"startxref\n999999\n"

        broken = tmp_path / "broken.pdf"
        broken.write_bytes(bytes(data))

        result = repair(broken, out)
        assert result.pages == 4
        assert page_widths(out) == [200, 201, 202, 203]

    def test_missing_file(self, tmp_path, out):
        with pytest.raises(InvalidDocument, match="No such file"):
            repair(tmp_path / "ghost.pdf", out)


class TestPdfToImages:
    def test_renders_every_page(self, sample, tmp_path):
        result = pdf_to_images(sample, tmp_path / "img", dpi=72)
        assert len(result.outputs) == 3
        assert all(p.exists() and p.stat().st_size > 0 for p in result.outputs)

    def test_page_selection(self, sample10, tmp_path):
        result = pdf_to_images(sample10, tmp_path / "img", dpi=48, pages="1-3")
        assert len(result.outputs) == 3

    @pytest.mark.parametrize("fmt", sorted(FORMATS))
    def test_every_format(self, sample, tmp_path, fmt):
        result = pdf_to_images(sample, tmp_path / fmt, dpi=48, fmt=fmt, pages="1")
        assert result.outputs[0].suffix == FORMATS[fmt][1]

    def test_dpi_controls_pixel_size(self, sample, tmp_path):
        from PIL import Image

        low = pdf_to_images(sample, tmp_path / "lo", dpi=36, pages="1").outputs[0]
        high = pdf_to_images(sample, tmp_path / "hi", dpi=144, pages="1").outputs[0]
        with Image.open(low) as small, Image.open(high) as large:
            assert large.width > small.width * 3

    def test_grayscale(self, sample, tmp_path):
        result = pdf_to_images(
            sample, tmp_path / "gray", dpi=48, fmt="jpeg", grayscale=True, pages="1"
        )
        assert result.outputs[0].exists()

    def test_filename_template(self, sample, tmp_path):
        result = pdf_to_images(sample, tmp_path / "img", dpi=48, template="p{page}{ext}")
        assert [p.name for p in result.outputs] == ["p1.png", "p2.png", "p3.png"]

    def test_unknown_format(self, sample, tmp_path):
        with pytest.raises(UnsupportedOperation, match="Unknown image format"):
            pdf_to_images(sample, tmp_path / "img", fmt="gif")

    @pytest.mark.parametrize("dpi", [0, 5, 2000])
    def test_dpi_bounds(self, sample, tmp_path, dpi):
        with pytest.raises(InvalidDocument, match="between 12 and 1200"):
            pdf_to_images(sample, tmp_path / "img", dpi=dpi)


class TestImagesToPdf:
    @pytest.fixture
    def photos(self, tmp_path):
        from PIL import Image

        folder = tmp_path / "photos"
        folder.mkdir()
        for index in (1, 2, 10):
            Image.new("RGB", (120, 90), (index * 20, 100, 150)).save(
                folder / f"shot{index}.png"
            )
        return folder

    def test_one_page_per_image(self, photos, out):
        result = images_to_pdf([photos], out)
        assert result.pages == 3
        assert len(page_widths(out)) == 3

    def test_directory_contents_sort_naturally(self, photos, out):
        result = images_to_pdf([photos], out)
        assert result.pages == 3  # shot1, shot2, shot10 — not shot1, shot10, shot2

    @pytest.mark.parametrize("size", sorted(PAGE_SIZES))
    def test_named_page_sizes(self, photos, tmp_path, size):
        target = tmp_path / f"{size}.pdf"
        images_to_pdf([photos], target, page_size=size)
        expected = PAGE_SIZES[size][0]
        assert abs(page_widths(target)[0] - expected) < expected * 0.05

    def test_auto_sizes_to_the_image(self, photos, out):
        images_to_pdf([photos], out, page_size="auto", dpi=120)
        assert page_widths(out)[0] == pytest.approx(120 / 120 * 72, abs=2)

    def test_margin_shrinks_the_image(self, photos, tmp_path):

        tight = tmp_path / "tight.pdf"
        roomy = tmp_path / "roomy.pdf"
        images_to_pdf([photos], tight, page_size="a4", margin=0)
        images_to_pdf([photos], roomy, page_size="a4", margin=72)
        assert page_widths(tight) == page_widths(roomy)  # same page, smaller content
        assert roomy.stat().st_size != tight.stat().st_size

    def test_unknown_page_size(self, photos, out):
        with pytest.raises(UnsupportedOperation, match="Unknown page size"):
            images_to_pdf([photos], out, page_size="a99")

    def test_missing_input(self, tmp_path, out):
        with pytest.raises(InvalidDocument, match="No such file"):
            images_to_pdf([tmp_path / "ghost.png"], out)

    def test_empty_directory(self, tmp_path, out):
        (tmp_path / "empty").mkdir()
        with pytest.raises(InvalidDocument, match="No image files"):
            images_to_pdf([tmp_path / "empty"], out)

    def test_non_image_file(self, sample, out):
        with pytest.raises(InvalidDocument, match="Could not read image"):
            images_to_pdf([sample], out)


class TestRoundTrip:
    def test_pdf_to_images_and_back(self, sample, tmp_path, out):
        rendered = pdf_to_images(sample, tmp_path / "frames", dpi=72)
        result = images_to_pdf(rendered.outputs, out)
        assert result.pages == 3


@pytest.fixture
def scanned(tmp_path):
    """A PDF holding one large, Flate-encoded RGB image — a synthetic scan.

    Built by hand rather than through `images_to_pdf`, because Pillow's PDF
    writer already emits JPEG. To exercise the lossy path honestly the source
    image has to start out losslessly encoded, the way a real scanner output
    or an export from an image editor does.
    """
    import random
    import zlib

    import pikepdf

    width, height = 600, 400
    rng = random.Random(0)
    # Smooth-ish gradients with noise: compresses poorly with Flate, well with
    # JPEG. Pure noise would be unrealistic and pure flat colour trivial.
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels += bytes(
                (
                    (x * 255 // width + rng.randint(0, 12)) & 0xFF,
                    (y * 255 // height + rng.randint(0, 12)) & 0xFF,
                    ((x + y) * 255 // (width + height) + rng.randint(0, 12)) & 0xFF,
                )
            )

    pdf = pikepdf.new()
    image = pikepdf.Stream(pdf, zlib.compress(bytes(pixels), 9))
    image.Type = pikepdf.Name.XObject
    image.Subtype = pikepdf.Name.Image
    image.Width = width
    image.Height = height
    image.ColorSpace = pikepdf.Name.DeviceRGB
    image.BitsPerComponent = 8
    image.Filter = pikepdf.Name.FlateDecode

    page = pdf.add_blank_page(page_size=(width, height))
    page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=image))
    page.Contents = pikepdf.Stream(
        pdf, f"q {width} 0 0 {height} 0 0 cm /Im0 Do Q".encode()
    )

    target = tmp_path / "scan.pdf"
    pdf.save(str(target))
    return target


class TestImageRecompression:
    """The lossy path — where a 40 MB scan is supposed to become a 3 MB one."""

    def test_lossless_leaves_the_image_alone(self, scanned, out):
        result = optimize(scanned, out)
        assert result.details["images_recompressed"] == 0

    def test_recompression_replaces_the_image(self, scanned, out):
        result = optimize(scanned, out, image_quality=60)
        assert result.details["images_recompressed"] == 1

    def test_recompression_actually_shrinks_the_file(self, scanned, out):
        result = optimize(scanned, out, image_quality=60)
        assert result.output_bytes < result.input_bytes
        assert result.details["bytes_saved"] > 0

    def test_lower_quality_yields_a_smaller_file(self, scanned, tmp_path):
        low = tmp_path / "low.pdf"
        high = tmp_path / "high.pdf"
        optimize(scanned, low, image_quality=20)
        optimize(scanned, high, image_quality=95)
        assert low.stat().st_size < high.stat().st_size

    def test_max_dpi_downsamples(self, scanned, tmp_path):
        """The page is 600pt wide holding a 600px image — 72 DPI effective."""
        import pikepdf

        target = tmp_path / "small.pdf"
        optimize(scanned, target, image_quality=80, max_dpi=36)
        with pikepdf.open(str(target)) as pdf:
            image = next(iter(pdf.pages[0].images.values()))
            assert int(image.Width) < 600

    def test_downsampling_is_skipped_when_already_below_the_target(
        self, scanned, tmp_path
    ):
        import pikepdf

        target = tmp_path / "same.pdf"
        optimize(scanned, target, image_quality=80, max_dpi=300)
        with pikepdf.open(str(target)) as pdf:
            image = next(iter(pdf.pages[0].images.values()))
            assert int(image.Width) == 600

    def test_result_is_still_a_readable_pdf(self, scanned, out):
        optimize(scanned, out, image_quality=50)
        assert len(page_widths(out)) == 1

    def test_transparent_images_are_left_alone(self, tmp_path, out):
        """JPEG has no alpha channel, so an image with a soft mask must be skipped."""
        import zlib

        import pikepdf

        pdf = pikepdf.new()
        width = height = 200
        image = pikepdf.Stream(pdf, zlib.compress(bytes(width * height * 3), 9))
        image.Type = pikepdf.Name.XObject
        image.Subtype = pikepdf.Name.Image
        image.Width, image.Height = width, height
        image.ColorSpace = pikepdf.Name.DeviceRGB
        image.BitsPerComponent = 8
        image.Filter = pikepdf.Name.FlateDecode

        mask = pikepdf.Stream(pdf, zlib.compress(bytes(width * height), 9))
        mask.Type = pikepdf.Name.XObject
        mask.Subtype = pikepdf.Name.Image
        mask.Width, mask.Height = width, height
        mask.ColorSpace = pikepdf.Name.DeviceGray
        mask.BitsPerComponent = 8
        mask.Filter = pikepdf.Name.FlateDecode
        image.SMask = mask

        page = pdf.add_blank_page(page_size=(width, height))
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=image))
        page.Contents = pikepdf.Stream(pdf, b"q 200 0 0 200 0 0 cm /Im0 Do Q")

        source = tmp_path / "transparent.pdf"
        pdf.save(str(source))

        result = optimize(source, out, image_quality=40)
        assert result.details["images_recompressed"] == 0
