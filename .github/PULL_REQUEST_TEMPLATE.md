## What this changes

<!-- One or two sentences. Link the issue if there is one: "Fixes #12". -->

## Why

<!-- What problem does it solve? If it changes existing behaviour, say what
     and why the new behaviour is better. -->

## Checklist

- [ ] Tests cover the change (including the failure cases, not just the happy path)
- [ ] `make check` passes locally — tests, ruff, mypy
- [ ] `CHANGELOG.md` updated under `## [Unreleased]`
- [ ] Docstrings and `--help` text updated if the interface changed
- [ ] README updated if this adds or changes a command

## For a new operation

- [ ] Added to `core/` and exported from `core/__init__.py`
- [ ] CLI command added, reusing the shared options in `cli/options.py`
- [ ] Entry added to `web/tools.py` so it appears in the web UI
- [ ] Page selection goes through `parse_pages` rather than a bespoke syntax
