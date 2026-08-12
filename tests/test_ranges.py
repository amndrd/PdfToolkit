"""The page-range dialect — the one piece every operation depends on."""

from __future__ import annotations

import pytest

from recto.errors import InvalidPageRange
from recto.ranges import describe_selection, format_pages, parse_pages


class TestParsing:
    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            ("1", [0]),
            ("1-3", [0, 1, 2]),
            ("1-3,5", [0, 1, 2, 4]),
            ("1 - 3 , 5", [0, 1, 2, 4]),
            ("2-", [1, 2, 3, 4]),
            ("-3", [0, 1, 2]),
            ("last", [4]),
            ("first", [0]),
            ("first-last", [0, 1, 2, 3, 4]),
            ("all", [0, 1, 2, 3, 4]),
            ("*", [0, 1, 2, 3, 4]),
            ("odd", [0, 2, 4]),
            ("even", [1, 3]),
            ("3-last", [2, 3, 4]),
        ],
    )
    def test_forms(self, spec, expected):
        assert parse_pages(spec, 5) == expected

    def test_none_and_blank_mean_everything(self):
        assert parse_pages(None, 3) == [0, 1, 2]
        assert parse_pages("   ", 3) == [0, 1, 2]

    def test_whitespace_and_case_are_forgiven(self):
        assert parse_pages(" 1 - 2 , LAST ", 5) == parse_pages("1-2,last", 5)

    def test_descending_ranges_reverse(self):
        assert parse_pages("3-1", 5) == [2, 1, 0]

    def test_order_is_preserved(self):
        """What makes `extract -p 3,1,2` reorder as well as extract."""
        assert parse_pages("3,1,2", 5) == [2, 0, 1]

    def test_duplicates_are_preserved(self):
        assert parse_pages("1,1,1", 5) == [0, 0, 0]

    def test_unique_drops_repeats_keeping_first_position(self):
        assert parse_pages("3,1,3", 5, unique=True) == [2, 0]

    def test_sort_forces_document_order(self):
        assert parse_pages("3,1,2", 5, sort=True) == [0, 1, 2]

    def test_empty_parts_are_skipped(self):
        assert parse_pages("1,,2", 5) == [0, 1]


class TestErrors:
    @pytest.mark.parametrize("spec", ["99", "1-99", "0", "0-2", "-99"])
    def test_out_of_bounds(self, spec):
        with pytest.raises(InvalidPageRange):
            parse_pages(spec, 5)

    @pytest.mark.parametrize("spec", ["abc", "1-2-3", "1..3", "!", "1-abc"])
    def test_malformed(self, spec):
        with pytest.raises(InvalidPageRange):
            parse_pages(spec, 5)

    def test_message_names_the_bound(self):
        with pytest.raises(InvalidPageRange, match="the document has 5 pages"):
            parse_pages("9", 5)

    def test_message_explains_one_based_numbering(self):
        with pytest.raises(InvalidPageRange, match="numbered from 1"):
            parse_pages("0", 5)

    def test_empty_document(self):
        with pytest.raises(InvalidPageRange, match="no pages"):
            parse_pages("1", 0)

    def test_allow_empty_permits_an_empty_selection(self):
        assert parse_pages("even", 1, allow_empty=True) == []

    def test_empty_selection_is_an_error_by_default(self):
        with pytest.raises(InvalidPageRange, match="selects no pages"):
            parse_pages("even", 1)


class TestFormatting:
    @pytest.mark.parametrize(
        ("indices", "expected"),
        [
            ([], "none"),
            ([0], "1"),
            ([0, 1], "1,2"),
            ([0, 1, 2], "1-3"),
            ([0, 1, 2, 4], "1-3,5"),
            ([0, 2, 4], "1,3,5"),
            ([0, 1, 2, 4, 7, 8], "1-3,5,8,9"),
        ],
    )
    def test_compact_output(self, indices, expected):
        assert format_pages(indices) == expected

    def test_sorts_and_deduplicates(self):
        assert format_pages([4, 0, 1, 0, 2]) == "1-3,5"

    def test_round_trips_through_the_parser(self):
        indices = [0, 1, 2, 5, 9]
        assert parse_pages(format_pages(indices), 10) == indices


class TestDescribeSelection:
    def test_reads_as_a_sentence(self):
        assert describe_selection([0, 1, 2], 10) == "3 of 10 pages (1-3)"

    def test_plural_agrees_with_the_total_not_the_selection(self):
        assert describe_selection([0], 3) == "1 of 3 pages (1)"
        assert describe_selection([0], 1) == "1 of 1 page (1)"
