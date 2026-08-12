"""The I/O guarantees: safe reads, atomic writes, no accidental clobbering."""

from __future__ import annotations

import pytest

from conftest import make_pdf
from recto.core.document import (
    atomic_output,
    collect_pdfs,
    human_size,
    load_pdf,
    page_count,
    prepare_output,
)
from recto.errors import (
    InvalidDocument,
    OutputExists,
    PasswordRequired,
    WrongPassword,
)


class TestLoading:
    def test_reads_pages(self, sample):
        loaded = load_pdf(sample)
        assert loaded.page_count == 3
        assert loaded.size == sample.stat().st_size
        assert loaded.path == sample

    def test_buffers_the_whole_file(self, sample):
        """The buffering is what makes --in-place safe; assert it explicitly."""
        loaded = load_pdf(sample)
        assert loaded.data == sample.read_bytes()

    def test_missing_file(self, tmp_path):
        with pytest.raises(InvalidDocument, match="No such file"):
            load_pdf(tmp_path / "ghost.pdf")

    def test_directory_instead_of_file(self, tmp_path):
        with pytest.raises(InvalidDocument, match="is a directory"):
            load_pdf(tmp_path)

    def test_empty_file(self, tmp_path):
        empty = tmp_path / "empty.pdf"
        empty.write_bytes(b"")
        with pytest.raises(InvalidDocument, match="is empty"):
            load_pdf(empty)

    def test_not_a_pdf(self, tmp_path):
        fake = tmp_path / "notes.pdf"
        fake.write_bytes(b"just some text, definitely not a PDF" * 40)
        with pytest.raises(InvalidDocument, match="does not look like a PDF"):
            load_pdf(fake)

    def test_suggests_repair_for_damaged_files(self, tmp_path):
        fake = tmp_path / "broken.pdf"
        fake.write_bytes(b"just some text" * 40)
        with pytest.raises(InvalidDocument) as info:
            load_pdf(fake)
        assert "recto repair" in str(info.value)


class TestEncryptedInputs:
    def test_password_opens_it(self, locked):
        assert load_pdf(locked, "s3cret").page_count == 3

    def test_missing_password(self, locked):
        with pytest.raises(PasswordRequired, match="--password"):
            load_pdf(locked)

    def test_wrong_password(self, locked):
        with pytest.raises(WrongPassword):
            load_pdf(locked, "hunter2")

    def test_page_count_helper(self, sample):
        assert page_count(sample) == 3


class TestOutputGuards:
    def test_refuses_to_clobber(self, tmp_path, sample):
        existing = tmp_path / "taken.pdf"
        existing.write_bytes(b"%PDF-1.7\n")
        with pytest.raises(OutputExists, match="--force"):
            prepare_output(existing)

    def test_overwrite_allows_it(self, tmp_path):
        existing = tmp_path / "taken.pdf"
        existing.write_bytes(b"%PDF-1.7\n")
        assert prepare_output(existing, overwrite=True) == existing

    def test_rejects_a_directory_destination(self, tmp_path):
        with pytest.raises(InvalidDocument, match="is a directory"):
            prepare_output(tmp_path)

    def test_creates_missing_parents(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "out.pdf"
        prepare_output(target)
        assert target.parent.is_dir()


class TestAtomicWrites:
    def test_content_lands(self, tmp_path):
        target = tmp_path / "out.bin"
        with atomic_output(target) as stream:
            stream.write(b"hello")
        assert target.read_bytes() == b"hello"

    def test_failure_leaves_no_output(self, tmp_path):
        target = tmp_path / "out.bin"
        with pytest.raises(RuntimeError), atomic_output(target) as stream:
            stream.write(b"partial")
            raise RuntimeError("boom")
        assert not target.exists()

    def test_failure_leaves_the_previous_version_intact(self, tmp_path):
        target = tmp_path / "out.bin"
        target.write_bytes(b"the good version")
        with pytest.raises(RuntimeError), atomic_output(target, overwrite=True) as stream:
            stream.write(b"the bad version")
            raise RuntimeError("boom")
        assert target.read_bytes() == b"the good version"

    def test_no_temporary_files_are_left_behind(self, tmp_path):
        target = tmp_path / "out.bin"
        with atomic_output(target) as stream:
            stream.write(b"hello")
        assert [p.name for p in tmp_path.iterdir()] == ["out.bin"]


class TestCollectingInputs:
    def test_files_keep_their_given_order(self, tmp_path):
        first = make_pdf(tmp_path / "z.pdf", 1)
        second = make_pdf(tmp_path / "a.pdf", 1)
        assert collect_pdfs([first, second]) == [first, second]

    def test_directories_sort_naturally(self, tmp_path):
        folder = tmp_path / "scans"
        for number in (1, 2, 10, 20):
            make_pdf(folder / f"page{number}.pdf", 1)
        names = [p.name for p in collect_pdfs([folder])]
        assert names == ["page1.pdf", "page2.pdf", "page10.pdf", "page20.pdf"]

    def test_recursive_reaches_subdirectories(self, tmp_path):
        make_pdf(tmp_path / "top.pdf", 1)
        make_pdf(tmp_path / "sub" / "deep.pdf", 1)
        assert len(collect_pdfs([tmp_path], recursive=True)) == 2
        assert len(collect_pdfs([tmp_path])) == 1

    def test_empty_directory(self, tmp_path):
        (tmp_path / "nothing").mkdir()
        with pytest.raises(InvalidDocument, match="No PDF files found"):
            collect_pdfs([tmp_path / "nothing"])

    def test_no_inputs(self):
        with pytest.raises(InvalidDocument, match="No input files"):
            collect_pdfs([])


class TestHumanSize:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, "0 B"),
            (999, "999 B"),
            (1024, "1.0 KB"),
            (1536, "1.5 KB"),
            (1024**2, "1.0 MB"),
            (1024**3, "1.0 GB"),
            (1024**4, "1.0 TB"),
        ],
    )
    def test_units(self, value, expected):
        assert human_size(value) == expected


class TestOptionalDependencies:
    def test_present_module_is_returned(self):
        from recto.core.document import require_optional

        assert require_optional("json", "Testing", "dev").__name__ == "json"

    def test_missing_module_names_the_extra(self):
        from recto.core.document import require_optional
        from recto.errors import MissingDependency

        with pytest.raises(MissingDependency) as info:
            require_optional("no_such_module_xyz", "Some feature", "images")
        assert "recto[images]" in str(info.value)
        assert "Some feature" in str(info.value)

    def test_submodule_reports_its_installable_name(self):
        """`PIL.Image` is the import path; `Pillow` is what pip installs."""
        from recto.core.document import require_optional
        from recto.errors import MissingDependency

        with pytest.raises(MissingDependency) as info:
            require_optional("PIL.NotAThing.Nested", "Image handling", "images")
        assert "Pillow" in str(info.value)
        assert "PIL.NotAThing" not in str(info.value)
