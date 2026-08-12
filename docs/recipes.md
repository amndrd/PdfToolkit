# Recipes

Real tasks, solved. Each one is a problem people actually have, not a tour of
the flags — for those, `recto <command> --help`.

- [Fixing scans](#fixing-scans)
- [Preparing documents to send](#preparing-documents-to-send)
- [Assembling documents](#assembling-documents)
- [Taking things apart](#taking-things-apart)
- [Batch work in the shell](#batch-work-in-the-shell)
- [Using Recto from Python](#using-recto-from-python)

---

## Fixing scans

### The pages are sideways

```console
recto rotate scan.pdf -d 90 --in-place
```

If only some pages are wrong, name them. `-d -90` turns the other way:

```console
recto rotate scan.pdf -d -90 -p 2,4,6 --in-place
```

If the pages disagree with each other — some rotated, some not — set an
absolute rotation instead of adding to what is there:

```console
recto rotate scan.pdf -d 0 --absolute --in-place
```

### Double-sided scan, backs in reverse order

You fed the stack once, flipped it, fed it again. Fronts are pages 1, 3, 5 …
in the right order; backs are 2, 4, 6 … in the wrong one.

```console
recto reverse scan.pdf -p even -o fixed.pdf
```

`-p even` reverses the even pages *among themselves* and leaves the odd pages
where they are.

### The scan is enormous

```console
recto compress scan.pdf --preset ebook -o small.pdf
```

`ebook` re-encodes embedded images at quality 75 and caps them at 150 DPI —
fine for reading on screen. Use `screen` to go smaller, `print` to stay
printable. Check what you got before deleting the original:

```console
recto info small.pdf
```

If the file is already mostly text, skip the preset entirely: the lossless
pass often takes 10–20% off with no quality cost at all.

```console
recto compress report.pdf -o smaller.pdf
```

### A blank page snuck in

```console
recto to-images suspect.pdf -o /tmp/preview --dpi 40   # look at them
recto delete suspect.pdf -p 7 -o clean.pdf
```

### The file will not open

```console
recto repair broken.pdf -o fixed.pdf
```

This rebuilds the cross-reference table through qpdf, which recovers most
truncated downloads and half-written files.

---

## Preparing documents to send

### Strip identifying metadata

PDF metadata routinely carries a real name, a local file path (`/Users/you/…`)
and the software used. Before sending anything to a stranger:

```console
recto info contract.pdf              # see what is in there
recto meta strip contract.pdf -o anonymous.pdf
```

This clears both the info dictionary and the XMP packet. Tools that clear only
the first leave the author's name recoverable from the second.

### Password-protect a document

```console
recto encrypt tax-return.pdf -o protected.pdf
```

It prompts for the password twice and uses AES-256.

To let anyone open it while discouraging editing — remembering that permission
flags are advisory and any reader may ignore them:

```console
recto encrypt report.pdf -u "" --owner-password boss --allow print,copy -o report-ro.pdf
```

### Send only part of a document

```console
recto extract contract.pdf -p 1,4-6 -o excerpt.pdf
```

### One PDF, small enough to email

```console
recto compress deck.pdf --preset screen --strip-metadata -o deck-small.pdf
```

---

## Assembling documents

### Cover + body + appendix

```console
recto merge cover.pdf body.pdf appendix.pdf -o final.pdf
```

Each source gets a bookmark, so the reader can still see where the parts
begin. `--no-outline` turns that off.

### Merge, but only part of one file

```console
recto merge cover.pdf report.pdf:2-10 appendix.pdf -o final.pdf
```

The `:2-10` fragment takes a page range from that file only.

### A folder of scans, in the right order

```console
recto merge ./scans -o combined.pdf
```

Directory contents are sorted naturally, so `page2.pdf` precedes `page10.pdf`
— which plain alphabetical sorting gets wrong.

### Add a cover to an existing document

```console
recto insert report.pdf cover.pdf --at 1 -o final.pdf
```

### Photos into a PDF

```console
recto from-images ./photos -o album.pdf
recto from-images ./receipts -o receipts.pdf --page-size a4 --margin 36
```

### Print several copies of a form

```console
recto duplicate form.pdf -p all -n 4 -o five-copies.pdf
```

---

## Taking things apart

### One file per chapter

```console
recto split book.pdf -o chapters/ --outline
```

Only works if the book has bookmarks; check with `recto info book.pdf`. See
the plan before committing:

```console
recto split book.pdf -o chapters/ --outline --dry-run
```

Name the outputs after the chapters:

```console
recto split book.pdf -o chapters/ --outline --template "{index:02d}-{label}.pdf"
```

### Fixed-size chunks, for an upload limit

```console
recto split big.pdf -o parts/ --every 20
```

### Pull out specific sections

```console
recto split report.pdf -o sections/ --range 1-4 --range 5-12 --range 13-
```

### Every page as its own file

```console
recto split form.pdf -o pages/ --every 1
```

### Turn pages into images

```console
recto to-images slides.pdf -o thumbnails/ --dpi 72
recto to-images poster.pdf -o print/ --dpi 300 --format tiff
```

---

## Batch work in the shell

Every command supports `--json`, and failures get distinct exit codes, so
Recto composes properly.

### Compress every PDF in a folder

```console
for f in *.pdf; do
  recto compress "$f" --preset ebook -o "compressed/$f"
done
```

### Only act on documents above a page count

```console
for f in *.pdf; do
  pages=$(recto info "$f" --json | jq .pages)
  if [ "$pages" -gt 50 ]; then
    recto split "$f" -o "parts/${f%.pdf}/" --every 25
  fi
done
```

### Find the encrypted files in a directory

```console
for f in *.pdf; do
  recto info "$f" --json 2>/dev/null | jq -e '.security.encrypted' >/dev/null \
    && echo "encrypted: $f"
done
```

### Branch on the kind of failure

| Code | Meaning |
| --- | --- |
| 0 | success |
| 2 | invalid page range |
| 3 | password required |
| 4 | wrong password |
| 5 | output exists (pass `--force`) |
| 6 | not a readable PDF |
| 7 | operation does not apply to this document |
| 8 | an optional dependency is missing |

```console
recto decrypt "$f" -o out.pdf --password "$PW"
case $? in
  0) echo "unlocked" ;;
  4) echo "wrong password, trying the next one" ;;
  7) echo "was not encrypted to begin with" ;;
  *) echo "gave up on $f" ;;
esac
```

---

## Using Recto from Python

The CLI is a thin shell over `recto.core`. Every function takes paths, does
one thing, and returns an `OperationResult`.

```python
from pathlib import Path

from recto.core import describe, merge, optimize, split

# Merge every PDF in a folder, newest last
folder = Path("scans")
files = sorted(folder.glob("*.pdf"), key=lambda p: p.stat().st_mtime)
result = merge(files, "combined.pdf")
print(result.summary, "|", result.size_delta)

# Split anything over 50 pages
for pdf in folder.glob("*.pdf"):
    if describe(pdf)["pages"] > 50:
        split(pdf, f"parts/{pdf.stem}", mode="every", every=25)

# Compress, and keep the smaller of the two
small = optimize("report.pdf", "report-small.pdf", image_quality=75, max_dpi=150)
if small.output_bytes >= small.input_bytes:
    Path("report-small.pdf").unlink()
```

Errors are typed, so you can react to the specific failure rather than parsing
a message:

```python
from recto.core import load_pdf
from recto.errors import InvalidDocument, PasswordRequired, WrongPassword


def try_passwords(path, candidates):
    """Return the password that opens `path`, or None."""
    for password in candidates:
        try:
            load_pdf(path, password)
            return password
        except WrongPassword:
            continue
        except PasswordRequired:
            continue
        except InvalidDocument:
            return None  # not a PDF at all; stop trying
    return None
```

Every operation accepts `password=` for encrypted inputs and `overwrite=` in
place of `--force`.

The full API is documented in the docstrings; `help(recto.core)` in a REPL is
the fastest way to browse it.
