# Contributing to Recto

Thanks for considering it. This document covers the setup, the conventions,
and what makes a change easy to accept.

## Setup

```console
git clone https://github.com/amndrd/PdfToolkit
cd PdfToolkit
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Check it works:

```console
pytest          # the whole suite, ~2 seconds
ruff check .    # lint
ruff format .   # format
mypy            # types
```

Or all of it at once:

```console
make check
```

## The shape of the project

```
src/recto/
  ranges.py      the page-range dialect — one syntax for the whole toolkit
  errors.py      typed exceptions, each carrying a CLI exit code
  core/          the operations: no printing, no prompting, no global state
    document.py    reading, atomic writing, output guards
    _subset.py     "build a document from these page indices"
    result.py      the one type every operation returns
  cli/           Typer commands, one module per area
  web/           FastAPI app; tools.py declares the UI
```

The rule that keeps this tidy: **`core/` never knows a front-end exists.** It
takes paths and options, returns an `OperationResult`, and raises typed
errors. The CLI and web layers are translation only.

## Adding an operation

Say you want `recto watermark`. Four steps, roughly 100 lines total:

1. **`src/recto/core/watermark.py`** — a function taking paths and options,
   returning an `OperationResult`. Use `load_pdf` to read and `write_pdf` to
   write, so you inherit password handling and atomic writes for free. Accept
   a `pages` string and run it through `parse_pages` rather than inventing a
   selection syntax.

2. **Export it** from `src/recto/core/__init__.py`.

3. **`src/recto/cli/commands/`** — add a Typer command. Reuse the shared
   options in `cli/options.py` (`opt.Password`, `opt.Force`, `opt.InPlace`, …)
   so your command behaves like every other one. Register the module in
   `cli/app.py`.

4. **`src/recto/web/tools.py`** — add one `Tool(...)` entry with its `Field`
   list and a small runner. The browser form is generated from it; you do not
   write any HTML or JavaScript.

Then tests, which is the part that actually matters.

## Tests

The suite builds its documents with `conftest.make_pdf`, which gives every
page a unique width (200, 201, 202, …). `page_widths(path)` then returns a
fingerprint of a document — so an assertion can pin down exactly *which* pages
survived an operation and *in what order*, not merely how many:

```python
def test_reorder(sample, out):
    reorder(sample, out, "3,1,2")
    assert page_widths(out) == [202, 200, 201]
```

Please prefer that style over asserting page counts. A count of 3 passes for
a great many wrong answers.

Also worth covering, because these are where the bugs have been:

- the empty and out-of-bounds page range,
- the encrypted input, with and without the password,
- the destination that already exists,
- `--in-place`.

Optional-dependency tests start with `pytest.importorskip`, so the suite stays
green on a base install.

## Style

- **Ruff** handles formatting and linting; `make check` runs both.
- **Type hints on everything public.** `mypy` runs in CI with
  `disallow_untyped_defs`.
- **Docstrings** in Google style, on every public function. Say what the
  arguments mean and what the failure modes are — the CLI help text and the
  README are generated from the same understanding.
- **Comments explain why, not what.** If a line is subtle — a workaround, a
  format quirk, an ordering constraint — say so. Otherwise let the code speak.
- **Error messages tell the user what to do next.** Compare:

  ```
  error: invalid page range
  error: Invalid page range '99': page 99 is out of bounds — the document has 3 pages.
  ```

## Commits and pull requests

- One logical change per PR. A bug fix and a refactor in the same diff take
  three times as long to review.
- Write commit subjects in the imperative: `add watermark command`, not
  `added` or `adds`.
- Update `CHANGELOG.md` under `## [Unreleased]`.
- CI must be green: tests on Linux, macOS and Windows across Python 3.10–3.14,
  plus lint, types, a base-install check and a build.

## Reporting bugs

The most useful bug report contains the exact command, the full error, your
`recto --version` and OS, and — if you can share it — the PDF that triggered
it. PDFs in the wild are gloriously malformed, and a real file that breaks
Recto is worth more than any description of one.

If the file is sensitive, say so; a page count and the output of
`recto info --json` on it is often enough to work from.

## Security

Please do not open a public issue for a security problem. See
[SECURITY.md](SECURITY.md).

## Licence

By contributing you agree that your contributions are licensed under the
[MIT Licence](LICENSE).
