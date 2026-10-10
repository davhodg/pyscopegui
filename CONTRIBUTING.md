# Contributing to pyscopegui

Bug reports, fixes and features are all welcome. pyscopegui is looked after by one person in their
own time, so there is no promised response time, but every issue and pull request is read.

Bugs and feature requests are issues. Security problems go through [SECURITY.md](SECURITY.md),
not a public issue. Everyone taking part is asked to follow the
[code of conduct](CODE_OF_CONDUCT.md).

## Policy

**Open an issue before large changes, to allow for discussion.** Trivial fixes can go straight to
a pull request.

**One change per pull request**, with commit messages that are short and say what changed.

**Tests with every change.** A fix comes with a test that fails without it. The full suite and
the linter must pass.

**A line in the changelog for anything a user would notice**, under *Unreleased* in
`pyscopegui/help/changelog.md`, in the group it belongs to: Added, Changed, Deprecated, Removed,
Fixed or Security. A release's description is taken from it.

**The manual says what the application does.** It is the Markdown in `pyscopegui/help`, shown
under *Help > Documentation* and read as it is on GitHub. A change to how something behaves
changes its page, and a new pane gets a page: the tests check that every pane is in it.

**Anything that drives an output asks to be chosen.** A signal generator is a real voltage on a
connector. It is off until somebody picks a waveform, and a new output of that kind does the
same.

**Dependencies stay few, and never GPL-only.** pyscopegui is Apache-2.0, and the Windows installer
bundles what it depends on, so a GPL-only package cannot be used. LGPL is fine as a separate,
replaceable package, as Qt is. A new dependency needs a reason in the pull request, and goes in
the *Built with* table in the README.

**Makers' libraries are never bundled.** A back end loads the instrument maker's own library at
run time, from wherever the maker's installer put it, and says so plainly when it is not there.
sigrok's protocol decoders are GPL-3.0: run them as a separate process, never import them.

**Licensing.** Contributions are made under the Apache License 2.0, as section 5 of the licence
says. Every source file starts with its SPDX licence line, and `tests/test_headers.py` checks it.
You are responsible for what you submit, however it was written.

## Setting up

Working on pyscopegui needs the same setup as running it from the source folder, plus the `[dev]`
extra -- pytest, pytest-xdist and ruff. The launcher installs pyscopegui from the source folder in
editable mode, so an edit takes effect the next time it starts.

After the launcher's first run, add them to its `.venv`:

```
.venv\Scripts\python -m pip install -e .[dev]
```

or, if `uv` was found and created the `.venv` (it has no pip of its own):

```
uv pip install --python .venv\Scripts\python.exe -e .[dev]
```

Without the launcher, `python -m venv .venv` first and then the pip line. On Linux the folder is
`.venv/bin` rather than `.venv\Scripts`.

## Tests and style

```
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format .
```

ruff sets the formatting, with lines of up to 100 characters. In prose -- the README, messages,
comments and docstrings -- sentences are separated by one space. Comments say *why*; the code
already says what.

`python build/icon.py` regenerates `pyscopegui.ico` and `pyscopegui.png` from the two SVGs in
`pyscopegui/resources`. Run it after editing either.

## Adding an instrument

A back end is one module in `pyscopegui/backends` holding a subclass of `Instrument`
(`pyscopegui/backends/base.py`), and one line in `BACKENDS` in `pyscopegui/backends/__init__.py`.
It sends `Block`s of evenly spaced samples, counted from when it started: the count is the clock,
so a block that arrives late is still drawn at the right time. `pyscopegui/backends/demo.py` is
the smallest example.

Samples stay in NumPy arrays from the maker's buffer to the plot. Nothing loops over samples in
Python.

## Continuous integration

`.github/workflows/ci.yml` runs the tests and lint on every push: the latest Python on Windows and
Linux, and the oldest supported Python on Linux as well. The installer is built only for a release
-- push a `v*` tag, or start the workflow by hand from the Actions tab.

## Building the Windows installer

`build.cmd` produces a self-contained Windows application, and an installer if a compiler for one
is present:

```
build.cmd            tests, notices, PyInstaller, checks, then setup.exe
build.cmd nosetup    stop after the checked application folder
build.cmd setup      only the installer, from the application folder already built
```

It runs the tests, regenerates `THIRD-PARTY-NOTICES.txt` from the installed package metadata,
builds a **one-directory** bundle with PyInstaller, checks the result, and then wraps it with
**Inno Setup**. The result is `dist\pyscopegui\pyscopegui.exe` and
`dist\pyscopegui-<version>-setup.exe`.

**LGPL components are bundled.** Qt (PySide6) is LGPL-3.0 and ships inside the installer. The LGPL
asks that it stays *replaceable*: hence the one-directory build, where it is separate DLLs a user
can substitute their own build of, rather than a single file.

**GPL-only components are intentionally excluded.** PySide6 ships Qt Charts, Qt Data
Visualization, Qt Graphs and the Virtual Keyboard in the same wheel as the LGPL modules. They are
excluded in `pyscopegui.spec`, and `build/check_build.py` fails the build if one appears anyway.

`build/check_build.py` also runs `pyscopegui.exe --selftest`, which imports every back end, to
find out what the bundle can import rather than guessing from file names.

## Versions and releases

The version is written once, as `__version__` in `pyscopegui/__init__.py`. A tag's installer is
named after the tag, and the build stops if the tag and `__version__` disagree. Any other build is
named `<version>-dev-<commit>`, so an installer that is not a release says so.

**Making a release:**

1. In `pyscopegui/help/changelog.md`, move what is under *Unreleased* to a heading for the
   version, `## [x.y.z] - YYYY-MM-DD`, and leave *Unreleased* above it.
2. Bump `__version__` in `pyscopegui/__init__.py` to match, commit and push.
3. Tag the same commit, `git tag v<version>`, and push the tag. CI runs the tests, builds the
   installer, and publishes it as a GitHub release whose description is that section of the
   changelog.

A tag whose run fails publishes nothing: delete it, fix, and tag again.
