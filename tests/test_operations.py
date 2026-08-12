"""The operations themselves.

Page identity is asserted through `page_widths`, which returns the ordered
widths of a document's pages. Because the fixtures give every page a unique
width, that list is an exact fingerprint of *which* pages survived an
operation and *in what order* — not merely how many.
"""

from __future__ import annotations

import pytest

from conftest import make_pdf, page_widths
from recto.core import (
    delete,
    duplicate,
    extract,
    insert,
    merge,
    reorder,
    reverse,
    rotate,
    split,
)
from recto.core.document import load_pdf
from recto.core.merge import parse_source
from recto.core.split import plan_split
from recto.errors import (
    InvalidDocument,
    InvalidPageRange,
    OutputExists,
    UnsupportedOperation,
)

# --------------------------------------------------------------------------- #
# merge
# --------------------------------------------------------------------------- #


class TestMerge:
    def test_concatenates_in_order(self, sample, other, out):
        result = merge([sample, other], out)
        assert page_widths(out) == [200, 201, 202, 500, 501]
        assert result.pages == 5

    def test_order_follows_the_arguments(self, sample, other, out):
        merge([other, sample], out)
        assert page_widths(out) == [500, 501, 200, 201, 202]

    def test_page_ranges_per_source(self, sample, other, out):
        merge([f"{sample}:1-2", other], out)
        assert page_widths(out) == [200, 201, 500, 501]

    def test_hash_also_introduces_a_range(self, sample, other, out):
        merge([f"{sample}#3", other], out)
        assert page_widths(out) == [202, 500, 501]

    def test_adds_a_bookmark_per_source(self, sample, other, out):
        merge([sample, other], out)
        titles = [item.title for item in load_pdf(out).reader.outline]
        assert titles == ["sample", "other"]

    def test_no_outline_flag(self, sample, other, out):
        merge([sample, other], out, outline=False)
        assert not load_pdf(out).reader.outline

    def test_needs_at_least_two(self, sample, out):
        with pytest.raises(InvalidDocument, match="at least two"):
            merge([sample], out)

    def test_refuses_to_overwrite_an_input(self, sample, other):
        with pytest.raises(InvalidDocument, match="both an input and the output"):
            merge([sample, other], sample)

    def test_reports_a_breakdown(self, sample, other, out):
        result = merge([f"{sample}:1", other], out)
        sources = result.details["sources"]
        assert [s["pages_taken"] for s in sources] == [1, 2]
        assert sources[0]["selection"] == "1"

    def test_existing_output_needs_force(self, sample, other, out):
        out.write_bytes(b"%PDF-1.7\n")
        with pytest.raises(OutputExists):
            merge([sample, other], out)
        merge([sample, other], out, overwrite=True)
        assert page_widths(out) == [200, 201, 202, 500, 501]


class TestParseSource:
    def test_plain_path(self):
        assert parse_source("report.pdf").pages is None

    def test_colon_fragment(self):
        source = parse_source("report.pdf:1-3")
        assert source.pages == "1-3"
        assert source.path.name == "report.pdf"

    def test_an_existing_path_always_wins(self, sample):
        """A real file called `a:b.pdf` must not be read as a page range."""
        weird = sample.parent / "a:b.pdf"
        weird.write_bytes(sample.read_bytes())
        assert parse_source(str(weird)).pages is None

    def test_windows_drive_letters_survive(self):
        assert parse_source(r"C:\scans\a.pdf").pages is None


# --------------------------------------------------------------------------- #
# split
# --------------------------------------------------------------------------- #


class TestSplit:
    def test_every(self, sample10, tmp_path):
        result = split(sample10, tmp_path / "parts", mode="every", every=4)
        assert [len(p["range"].split(",")) or 0 for p in result.details["parts"]]
        assert [p["pages"] for p in result.details["parts"]] == [4, 4, 2]
        assert page_widths(result.outputs[0]) == [200, 201, 202, 203]

    def test_into_distributes_the_remainder_first(self, sample10, tmp_path):
        result = split(sample10, tmp_path / "parts", mode="into", into=3)
        assert [p["pages"] for p in result.details["parts"]] == [4, 3, 3]

    def test_into_more_parts_than_pages(self, sample, tmp_path):
        with pytest.raises(InvalidPageRange, match="empty files"):
            split(sample, tmp_path / "parts", mode="into", into=99)

    def test_at_cuts_before_the_named_pages(self, sample10, tmp_path):
        result = split(sample10, tmp_path / "parts", mode="at", at="4,9")
        assert [p["range"] for p in result.details["parts"]] == ["1-3", "4-8", "9,10"]

    def test_at_page_one_is_rejected(self, sample10, tmp_path):
        with pytest.raises(InvalidPageRange, match="empty first file"):
            split(sample10, tmp_path / "parts", mode="at", at="1")

    def test_explicit_ranges(self, sample10, tmp_path):
        result = split(sample10, tmp_path / "parts", mode="ranges", ranges=["1-3", "8-"])
        assert len(result.outputs) == 2
        assert page_widths(result.outputs[1]) == [207, 208, 209]

    def test_outline(self, outlined, tmp_path):
        result = split(outlined, tmp_path / "chapters", mode="outline")
        assert [p["label"] for p in result.details["parts"]] == [
            "Chapter One",
            "Chapter Two",
            "Chapter Three",
        ]
        assert [p["pages"] for p in result.details["parts"]] == [3, 3, 3]

    def test_outline_without_bookmarks(self, sample, tmp_path):
        with pytest.raises(UnsupportedOperation, match="no bookmarks"):
            split(sample, tmp_path / "parts", mode="outline")

    def test_template_fields(self, sample10, tmp_path):
        result = split(
            sample10,
            tmp_path / "parts",
            mode="every",
            every=5,
            template="{stem}_{start}-{end}_{count}p.pdf",
        )
        assert [p.name for p in result.outputs] == [
            "sample10_1-5_5p.pdf",
            "sample10_6-10_5p.pdf",
        ]

    def test_template_slugifies_labels(self, outlined, tmp_path):
        result = split(outlined, tmp_path / "c", mode="outline", template="{label}.pdf")
        assert [p.name for p in result.outputs] == [
            "chapter-one.pdf",
            "chapter-two.pdf",
            "chapter-three.pdf",
        ]

    def test_template_rejects_unknown_fields(self, sample10, tmp_path):
        with pytest.raises(InvalidDocument, match="Available fields"):
            split(sample10, tmp_path / "p", mode="every", every=5, template="{nope}.pdf")

    def test_extension_is_added_when_missing(self, sample10, tmp_path):
        result = split(
            sample10, tmp_path / "p", mode="every", every=5, template="{index}"
        )
        assert all(p.suffix == ".pdf" for p in result.outputs)

    def test_planning_writes_nothing(self, sample10, tmp_path):
        parts = plan_split(load_pdf(sample10).reader, mode="every", every=3)
        assert [len(p.indices) for p in parts] == [3, 3, 3, 1]
        assert not (tmp_path / "parts").exists()

    @pytest.mark.parametrize(
        ("mode", "kwargs"),
        [
            ("every", {"every": 0}),
            ("into", {"into": 0}),
            ("at", {"at": ""}),
            ("ranges", {"ranges": []}),
        ],
    )
    def test_missing_parameters(self, sample10, tmp_path, mode, kwargs):
        with pytest.raises(InvalidPageRange):
            split(sample10, tmp_path / "parts", mode=mode, **kwargs)

    def test_every_page_separately(self, sample, tmp_path):
        result = split(sample, tmp_path / "pages", mode="every", every=1)
        assert len(result.outputs) == 3
        assert [page_widths(p) for p in result.outputs] == [[200], [201], [202]]


# --------------------------------------------------------------------------- #
# rotate / extract
# --------------------------------------------------------------------------- #


class TestRotate:
    def test_rotates_every_page(self, sample, out):
        result = rotate(sample, out, 90)
        assert result.details["rotations"] == {1: 90, 2: 90, 3: 90}

    def test_selection_only(self, sample, out):
        result = rotate(sample, out, 90, pages="1,3")
        assert set(result.details["rotations"]) == {1, 3}

    def test_accumulates_by_default(self, sample, out, tmp_path):
        rotate(sample, out, 90)
        again = rotate(out, tmp_path / "again.pdf", 90)
        assert again.details["rotations"][1] == 180

    def test_absolute_replaces(self, sample, out, tmp_path):
        rotate(sample, out, 270)
        again = rotate(out, tmp_path / "again.pdf", 90, absolute=True)
        assert again.details["rotations"][1] == 90

    def test_negative_normalises(self, sample, out):
        assert rotate(sample, out, -90).details["rotations"][1] == 270

    def test_full_turn_is_a_no_op(self, sample, out):
        assert rotate(sample, out, 360).details["rotations"][1] == 0

    @pytest.mark.parametrize("degrees", [45, 1, -30, 100])
    def test_rejects_non_quarter_turns(self, sample, out, degrees):
        with pytest.raises(InvalidPageRange, match="multiple of 90"):
            rotate(sample, out, degrees)

    def test_page_count_is_unchanged(self, sample, out):
        rotate(sample, out, 90, pages="1")
        assert page_widths(out) == [200, 201, 202]


class TestExtract:
    def test_takes_the_named_pages(self, sample10, out):
        extract(sample10, out, "1-3")
        assert page_widths(out) == [200, 201, 202]

    def test_honours_the_given_order(self, sample10, out):
        extract(sample10, out, "3,1")
        assert page_widths(out) == [202, 200]

    def test_keeps_duplicates(self, sample10, out):
        extract(sample10, out, "1,1")
        assert page_widths(out) == [200, 200]

    def test_unique_drops_them(self, sample10, out):
        extract(sample10, out, "1,1", unique=True)
        assert page_widths(out) == [200]

    def test_sort_forces_document_order(self, sample10, out):
        extract(sample10, out, "3,1", sort=True)
        assert page_widths(out) == [200, 202]

    def test_out_of_range(self, sample, out):
        with pytest.raises(InvalidPageRange):
            extract(sample, out, "99")


# --------------------------------------------------------------------------- #
# page manipulation
# --------------------------------------------------------------------------- #


class TestDelete:
    def test_removes_pages(self, sample, out):
        delete(sample, out, "2")
        assert page_widths(out) == [200, 202]

    def test_removes_several(self, sample10, out):
        delete(sample10, out, "1-3,10")
        assert page_widths(out) == [203, 204, 205, 206, 207, 208]

    def test_refuses_to_empty_the_document(self, sample, out):
        with pytest.raises(InvalidPageRange, match="would remove all"):
            delete(sample, out, "all")


class TestReorder:
    def test_explicit_order(self, sample, out):
        reorder(sample, out, "3,1,2")
        assert page_widths(out) == [202, 200, 201]

    def test_unlisted_pages_are_dropped(self, sample, out):
        reorder(sample, out, "3,1")
        assert page_widths(out) == [202, 200]

    def test_keep_unlisted_appends_them(self, sample, out):
        reorder(sample, out, "3", keep_unlisted=True)
        assert page_widths(out) == [202, 200, 201]

    def test_reports_dropped_count(self, sample, out):
        assert reorder(sample, out, "1").details["dropped"] == 2


class TestReverse:
    def test_whole_document(self, sample, out):
        reverse(sample, out)
        assert page_widths(out) == [202, 201, 200]

    def test_selection_swaps_within_itself(self, sample10, out):
        """The classic double-sided scan fix: only the backs move."""
        reverse(sample10, out, pages="even")
        assert page_widths(out) == [200, 209, 202, 207, 204, 205, 206, 203, 208, 201]

    def test_odd_pages_stay_put_when_reversing_evens(self, sample10, out):
        reverse(sample10, out, pages="even")
        widths = page_widths(out)
        assert [widths[i] for i in (0, 2, 4, 6, 8)] == [200, 202, 204, 206, 208]


class TestInsert:
    def test_appends_by_default(self, sample, other, out):
        insert(sample, other, out)
        assert page_widths(out) == [200, 201, 202, 500, 501]

    def test_at_the_front(self, sample, other, out):
        insert(sample, other, out, at=1)
        assert page_widths(out) == [500, 501, 200, 201, 202]

    def test_in_the_middle(self, sample, other, out):
        insert(sample, other, out, at=2)
        assert page_widths(out) == [200, 500, 501, 201, 202]

    def test_one_past_the_end_is_allowed(self, sample, other, out):
        insert(sample, other, out, at=4)
        assert page_widths(out) == [200, 201, 202, 500, 501]

    def test_subset_of_the_donor(self, sample, other, out):
        insert(sample, other, out, at=1, pages="2")
        assert page_widths(out) == [501, 200, 201, 202]

    @pytest.mark.parametrize("position", [0, 5, 99, -1])
    def test_out_of_bounds(self, sample, other, out, position):
        with pytest.raises(InvalidPageRange, match="valid positions"):
            insert(sample, other, out, at=position)


class TestDuplicate:
    def test_doubles_a_page_in_place(self, sample, out):
        duplicate(sample, out, "2")
        assert page_widths(out) == [200, 201, 201, 202]

    def test_multiple_extra_copies(self, sample, out):
        duplicate(sample, out, "1", times=3)
        assert page_widths(out) == [200, 200, 200, 200, 201, 202]

    def test_several_pages_at_once(self, sample, out):
        duplicate(sample, out, "1,3")
        assert page_widths(out) == [200, 200, 201, 202, 202]

    def test_times_must_be_positive(self, sample, out):
        with pytest.raises(InvalidDocument, match="at least 1"):
            duplicate(sample, out, "1", times=0)


# --------------------------------------------------------------------------- #
# Cross-cutting guarantees
# --------------------------------------------------------------------------- #


class TestInPlaceEditing:
    """Writing over the input is safe because inputs are buffered first."""

    def test_rotate_in_place(self, sample):
        result = rotate(sample, sample, 90, overwrite=True)
        assert result.details["rotations"] == {1: 90, 2: 90, 3: 90}
        assert page_widths(sample) == [200, 201, 202]

    def test_delete_in_place(self, sample):
        delete(sample, sample, "2", overwrite=True)
        assert page_widths(sample) == [200, 202]

    def test_repeated_in_place_edits_compose(self, sample):
        delete(sample, sample, "3", overwrite=True)
        reverse(sample, sample, overwrite=True)
        assert page_widths(sample) == [201, 200]


class TestEncryptedSources:
    """Every operation must accept a password for its input."""

    @pytest.mark.parametrize(
        ("operation", "args"),
        [
            (extract, ("1",)),
            (delete, ("2",)),
            (reorder, ("2,1",)),
        ],
    )
    def test_password_is_threaded_through(self, locked, out, operation, args):
        operation(locked, out, *args, password="s3cret")
        assert out.exists()

    def test_rotate_accepts_a_password(self, locked, out):
        rotate(locked, out, 90, password="s3cret")
        assert page_widths(out) == [200, 201, 202]

    def test_merge_accepts_a_password(self, locked, tmp_path, out):
        second = make_pdf(tmp_path / "second.pdf", 2, base_width=500, encrypt="s3cret")
        merge([locked, second], out, password="s3cret")
        assert page_widths(out) == [200, 201, 202, 500, 501]


class TestResultShape:
    def test_single_output_accessor(self, sample, out):
        assert extract(sample, out, "1").output == out

    def test_single_output_accessor_rejects_multiples(self, sample10, tmp_path):
        result = split(sample10, tmp_path / "parts", mode="every", every=5)
        with pytest.raises(ValueError, match=r"Use \.outputs"):
            _ = result.output

    def test_size_delta_reads_as_a_comparison(self, sample10, out):
        assert "->" in extract(sample10, out, "1").size_delta

    def test_is_json_serialisable(self, sample, out):
        import json

        payload = json.dumps(extract(sample, out, "1").to_dict())
        assert "outputs" in json.loads(payload)


class TestSummaries:
    """Summaries are shown verbatim in the CLI and the web UI alike."""

    def test_split_summary_omits_the_destination(self, sample10, tmp_path):
        """The web UI's destination is a temp path with no meaning to a user."""
        result = split(sample10, tmp_path / "parts", mode="every", every=5)
        assert str(tmp_path) not in result.summary
        assert result.summary == "Split sample10.pdf (10 pages) into 2 files"
        assert result.details["directory"] == str(tmp_path / "parts")

    def test_merge_summary_names_the_output(self, sample, other, out):
        assert merge([sample, other], out).summary == (
            "Merged 2 files into out.pdf (5 pages)"
        )
