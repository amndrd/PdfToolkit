# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — unreleased

First release.

### Added

- **Core library** (`recto.core`) — every operation as a plain function
  returning an `OperationResult`, with typed exceptions.
- **Merge** — concatenation with per-file page ranges (`report.pdf:2-10`),
  directory inputs with natural sorting, and a bookmark per source file.
- **Split** — five strategies: fixed chunks (`--every`), equal parts
  (`--into`), cut points (`--at`), explicit ranges (`--range`) and bookmarks
  (`--outline`). Filename templates and `--dry-run`.
- **Rotate** — lossless quarter-turns, relative or absolute, per page range.
- **Extract** — order-preserving page selection.
- **Page manipulation** — `delete`, `reorder`, `reverse`, `insert`,
  `duplicate`.
- **Security** — AES-256/AES-128/RC4 encryption with per-permission control,
  decryption, and security inspection.
- **Metadata** — `info`, `meta show`, `meta set`, `meta strip` (info
  dictionary *and* XMP).
- **Optimisation** — lossless recompression, lossy image re-encoding with
  presets, linearisation, and qpdf-backed `repair`.
- **Images** — `to-images` via PDFium, `from-images` with fixed or automatic
  page sizes.
- **CLI** — one page-range dialect across every command, `--json`, `--quiet`,
  `--in-place`, `--force`, and distinct exit codes per failure kind.
- **Web interface** — `recto serve`, an offline drag-and-drop UI bound to
  loopback, generated from a declarative tool registry. A centred drop card
  opens into the document itself: every page rendered as a thumbnail, tools
  grouped into five tabs above it, and page ranges chosen by clicking pages
  rather than typing expressions. Thumbnails render through PDFium, are cached
  per session and loaded lazily, so a 300-page document costs no more than a
  3-page one until you scroll.

[Unreleased]: https://github.com/amndrd/recto/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/amndrd/recto/releases/tag/v0.1.0
