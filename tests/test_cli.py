"""The command-line interface.

These tests exist because the CLI is where most users meet Recto: a wrong exit
code or a swallowed error is a bug even when the core library is perfect.
"""

from __future__ import annotations

import json
import sys

import pytest
from typer.testing import CliRunner

from conftest import make_pdf, page_widths
from recto import __version__
from recto.cli.app import app, main

runner = CliRunner()


def invoke(*args):
    """Run a command and return the Click result."""
    return runner.invoke(app, [str(arg) for arg in args])


class TestPlumbing:
    def test_version(self):
        result = invoke("--version")
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_help_lists_every_command(self):
        result = invoke("--help")
        for command in ("merge", "split", "rotate", "extract", "encrypt", "compress"):
            assert command in result.output

    def test_bare_invocation_shows_help(self):
        assert "Usage" in invoke().output

    @pytest.mark.parametrize(
        "command",
        [
            "merge",
            "split",
            "rotate",
            "extract",
            "delete",
            "reorder",
            "reverse",
            "insert",
            "duplicate",
            "encrypt",
            "decrypt",
            "info",
            "compress",
            "repair",
            "to-images",
            "from-images",
            "serve",
            "meta",
        ],
    )
    def test_every_command_has_help(self, command):
        result = invoke(command, "--help")
        assert result.exit_code == 0
        assert "Usage" in result.output


class TestCommands:
    def test_merge(self, sample, other, out):
        result = invoke("merge", sample, other, "-o", out)
        assert result.exit_code == 0
        assert page_widths(out) == [200, 201, 202, 500, 501]

    def test_merge_with_page_ranges(self, sample, other, out):
        invoke("merge", f"{sample}:1-2", other, "-o", out)
        assert page_widths(out) == [200, 201, 500, 501]

    def test_merge_a_directory(self, tmp_path, out):
        folder = tmp_path / "scans"
        for number in (1, 2, 10):
            make_pdf(folder / f"page{number}.pdf", 1, base_width=200 + number)
        invoke("merge", folder, "-o", out)
        assert page_widths(out) == [201, 202, 210]

    def test_split(self, sample10, tmp_path):
        result = invoke("split", sample10, "-o", tmp_path / "parts", "--every", 4)
        assert result.exit_code == 0
        assert len(list((tmp_path / "parts").glob("*.pdf"))) == 3

    def test_split_dry_run_writes_nothing(self, sample10, tmp_path):
        result = invoke(
            "split", sample10, "-o", tmp_path / "parts", "--into", 3, "--dry-run"
        )
        assert result.exit_code == 0
        assert not (tmp_path / "parts").exists()

    def test_split_needs_exactly_one_strategy(self, sample10, tmp_path):
        none = invoke("split", sample10, "-o", tmp_path / "p")
        both = invoke("split", sample10, "-o", tmp_path / "p", "--every", 2, "--into", 2)
        assert none.exit_code != 0
        assert both.exit_code != 0
        assert "exactly one" in none.output

    def test_rotate(self, sample, out):
        assert invoke("rotate", sample, "-d", 90, "-o", out).exit_code == 0

    def test_extract(self, sample10, out):
        invoke("extract", sample10, "-p", "3,1", "-o", out)
        assert page_widths(out) == [202, 200]

    def test_delete(self, sample, out):
        invoke("delete", sample, "-p", 2, "-o", out)
        assert page_widths(out) == [200, 202]

    def test_reorder(self, sample, out):
        invoke("reorder", sample, "--order", "3,1,2", "-o", out)
        assert page_widths(out) == [202, 200, 201]

    def test_reverse(self, sample, out):
        invoke("reverse", sample, "-o", out)
        assert page_widths(out) == [202, 201, 200]

    def test_insert(self, sample, other, out):
        invoke("insert", sample, other, "--at", 1, "-o", out)
        assert page_widths(out) == [500, 501, 200, 201, 202]

    def test_duplicate(self, sample, out):
        invoke("duplicate", sample, "-p", 1, "-n", 2, "-o", out)
        assert page_widths(out) == [200, 200, 200, 201, 202]

    def test_encrypt_and_decrypt(self, sample, tmp_path):
        locked = tmp_path / "locked.pdf"
        opened = tmp_path / "opened.pdf"
        assert invoke("encrypt", sample, "-u", "pw", "-o", locked).exit_code == 0
        assert invoke("decrypt", locked, "--password", "pw", "-o", opened).exit_code == 0
        assert page_widths(opened) == [200, 201, 202]

    def test_info(self, outlined):
        result = invoke("info", outlined)
        assert result.exit_code == 0
        assert "9" in result.output

    def test_compress(self, sample10, out):
        assert invoke("compress", sample10, "-o", out).exit_code == 0

    def test_compress_preset(self, sample10, out):
        assert invoke("compress", sample10, "--preset", "ebook", "-o", out).exit_code == 0

    def test_compress_rejects_unknown_preset(self, sample10, out):
        result = invoke("compress", sample10, "--preset", "tiny", "-o", out)
        assert result.exit_code != 0
        assert "Unknown preset" in result.output

    def test_compress_preset_conflicts_with_manual_quality(self, sample10, out):
        result = invoke("compress", sample10, "--preset", "ebook", "-q", 50, "-o", out)
        assert result.exit_code != 0

    def test_repair(self, sample, out):
        assert invoke("repair", sample, "-o", out).exit_code == 0

    def test_to_images(self, sample, tmp_path):
        result = invoke("to-images", sample, "-o", tmp_path / "img", "--dpi", 48)
        assert result.exit_code == 0
        assert len(list((tmp_path / "img").glob("*.png"))) == 3

    def test_meta_set_and_show(self, sample, out):
        invoke("meta", "set", sample, "--title", "Hello", "-o", out)
        result = invoke("meta", "show", out, "--json")
        assert json.loads(result.output)["title"] == "Hello"

    def test_meta_set_needs_a_field(self, sample, out):
        result = invoke("meta", "set", sample, "-o", out)
        assert result.exit_code != 0
        assert "Nothing to change" in result.output

    def test_meta_strip(self, tmp_path, out):
        source = make_pdf(tmp_path / "m.pdf", 2, metadata={"/Title": "Secret"})
        invoke("meta", "strip", source, "-o", out)
        assert json.loads(invoke("meta", "show", out, "--json").output)["title"] is None


class TestOutputModes:
    def test_json_is_machine_readable(self, sample, out):
        result = invoke("extract", sample, "-p", 1, "-o", out, "--json")
        payload = json.loads(result.output)
        assert payload["pages"] == 1
        assert payload["outputs"] == [str(out)]

    def test_quiet_prints_nothing(self, sample, out):
        result = invoke("extract", sample, "-p", 1, "-o", out, "--quiet")
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_in_place(self, sample):
        result = invoke("delete", sample, "-p", 2, "--in-place")
        assert result.exit_code == 0
        assert page_widths(sample) == [200, 202]

    def test_in_place_conflicts_with_output(self, sample, out):
        result = invoke("delete", sample, "-p", 2, "-o", out, "--in-place")
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_output_is_required(self, sample):
        result = invoke("delete", sample, "-p", 2)
        assert result.exit_code != 0
        assert "--in-place" in result.output

    def test_force_allows_overwriting(self, sample, out):
        invoke("extract", sample, "-p", 1, "-o", out)
        assert invoke("extract", sample, "-p", 2, "-o", out).exit_code != 0
        assert invoke("extract", sample, "-p", 2, "-o", out, "--force").exit_code == 0
        assert page_widths(out) == [201]


class TestExitCodes:
    """Distinct codes let shell scripts branch on the kind of failure.

    These go through `main()` rather than CliRunner, because translating
    exceptions into exit codes is exactly what `main()` does — testing the
    Typer app directly would skip the layer under test.
    """

    @staticmethod
    def run(
        monkeypatch,
        *args,
    ):
        monkeypatch.setattr(sys, "argv", ["recto", *[str(a) for a in args]])
        return main()

    def test_success(self, monkeypatch, sample):
        assert self.run(monkeypatch, "info", sample) == 0

    def test_bad_page_range(self, monkeypatch, sample, out):
        assert self.run(monkeypatch, "extract", sample, "-p", 99, "-o", out) == 2

    def test_password_required(self, monkeypatch, locked):
        assert self.run(monkeypatch, "info", locked) == 3

    def test_wrong_password(self, monkeypatch, locked):
        assert self.run(monkeypatch, "info", locked, "--password", "nope") == 4

    def test_output_exists(self, monkeypatch, sample, out):
        assert self.run(monkeypatch, "extract", sample, "-p", 1, "-o", out) == 0
        assert self.run(monkeypatch, "extract", sample, "-p", 1, "-o", out) == 5

    def test_invalid_document(self, monkeypatch, tmp_path):
        assert self.run(monkeypatch, "info", tmp_path / "ghost.pdf") == 6

    def test_unsupported_operation(self, monkeypatch, sample, out):
        assert self.run(monkeypatch, "decrypt", sample, "--password", "x", "-o", out) == 7

    def test_version_exits_cleanly(self, monkeypatch):
        assert self.run(monkeypatch, "--version") == 0

    def test_unknown_command_is_a_usage_error(self, monkeypatch):
        """Must be a clean 2, not an unhandled traceback."""
        assert self.run(monkeypatch, "definitely-not-a-command") == 2

    def test_unknown_option_is_a_usage_error(self, monkeypatch, sample):
        assert self.run(monkeypatch, "info", sample, "--nonsense") == 2

    def test_errors_do_not_pollute_stdout(self, monkeypatch, capsys, sample, out):
        """`recto ... --json > file` must not mix errors into the file."""
        assert self.run(monkeypatch, "extract", sample, "-p", 99, "-o", out) == 2
        captured = capsys.readouterr()
        assert "out of bounds" in captured.err
        assert "out of bounds" not in captured.out


class TestMarkupEscaping:
    """Rich treats [text] as a style tag; user content must be escaped.

    This is not cosmetic. The missing-dependency message ends with
    `pip install 'recto[web]'`, and unescaped it renders as `pip install
    'recto'` — instructions that silently do the wrong thing.
    """

    def test_extra_name_survives_in_the_install_hint(self, capsys):
        from recto.cli.render import render_error
        from recto.errors import MissingDependency

        render_error(MissingDependency("uvicorn", "The web interface", "web"))
        assert "recto[web]" in capsys.readouterr().err

    def test_brackets_in_filenames_survive(self, tmp_path, capsys):
        from recto.cli.render import render_result
        from recto.core.result import OperationResult

        path = tmp_path / "report [final].pdf"
        render_result(
            OperationResult(outputs=[path], pages=1, summary=f"Wrote {path.name}")
        )
        out = capsys.readouterr().out
        assert "report [final].pdf" in out

    def test_brackets_in_metadata_survive(self, tmp_path, out, capsys):
        from recto.cli.render import render_mapping
        from recto.core import read_metadata, set_metadata

        source = make_pdf(tmp_path / "m.pdf", 1)
        set_metadata(source, out, {"title": "Draft [v2]"})
        render_mapping("meta", read_metadata(out))
        assert "[v2]" in capsys.readouterr().out
