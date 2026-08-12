# Security Policy

## Reporting a vulnerability

Please report security issues privately, not as a public issue.

Use GitHub's [private vulnerability reporting][gh] on this repository
(Security → Report a vulnerability). You should get an acknowledgement within
a few days.

[gh]: https://github.com/amndrd/recto/security/advisories/new

Useful things to include: what an attacker can achieve, the steps to reproduce
it, the Recto version and OS, and a sample file if one is involved.

## Supported versions

The latest release is supported. Recto is pre-1.0; fixes land on `main` and
in the next release rather than being backported.

## Threat model

Recto parses untrusted input — PDFs are a rich, historically exploitable
format — and optionally runs a local HTTP server. What that means in practice:

**In scope**

- Anything that turns a malicious PDF into code execution, a file read or
  write outside the intended output path, or a hang that a normal-looking file
  can trigger.
- Anything letting a remote page or another machine reach the `recto serve`
  interface when it is bound to loopback: DNS rebinding, cross-origin requests,
  path traversal through upload names or result ids.
- Recto writing outside the paths it was told to write to.

**Out of scope**

- Weaknesses in PDF's own encryption. RC4-40 and RC4-128 are broken by design;
  they are offered for compatibility with old readers and documented as such.
- **Permission flags being ignorable.** In PDF, "may not print" and "may not
  copy" are advisory: the content is decrypted regardless and any reader can
  disregard the flags. This is how the format works, not a flaw in Recto.
- Running `recto serve --host 0.0.0.0` and finding it reachable. That flag
  exists for people who mean it, warns when used, and the interface has no
  authentication by design.
- Vulnerabilities in upstream libraries — please report those to
  [pypdf](https://github.com/py-pdf/pypdf),
  [pikepdf](https://github.com/pikepdf/pikepdf) or
  [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) directly. Tell us
  too if Recto needs a version bump or a workaround.

## What Recto does to stay safe

- **No network access.** Recto makes no outbound connections. The web UI ships
  its own CSS and JavaScript and sets a Content-Security-Policy of
  `default-src 'none'`, so the page cannot load anything external either.
- **Loopback only.** `recto serve` binds `127.0.0.1` and rejects requests whose
  `Host` header is not local — the defence against DNS rebinding — and refuses
  cross-origin requests.
- **No addressable filesystem.** Uploads are stored under generated ids in a
  temporary directory removed on shutdown. No request path is ever joined to a
  user-supplied string, and upload filenames are reduced to their basename.
- **Atomic writes.** Output goes to a temporary file that is moved into place
  only when complete, so an interrupted or failed run cannot destroy an
  existing file.
- **Input buffering.** Files are read fully before anything is written, which
  is what makes `--in-place` safe.
