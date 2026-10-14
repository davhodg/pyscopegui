# Security policy

## Reporting a vulnerability

Please report it privately rather than in a public issue:
**[report a vulnerability](https://github.com/davhodg/pyscopegui/security/advisories/new)**,
which is also under the repository's *Security* tab.

Say what you found, how to make it happen, and which version or commit you
were running -- *Help > About pyscopegui* has a box to copy that from.

pyscopegui is looked after by one person in their own time, so there is no
promised response time. Every report is read and answered, the fix and the
advisory are published together, and you are credited in the advisory unless
you would rather not be.

## Versions that get fixes

The latest release and `master`. Older releases are not patched: upgrading
is the fix.

## What is and is not a vulnerability

pyscopegui loads an instrument maker's library and calls into it, on purpose.
It looks for that library where the maker's installer puts it, or at a path
you give in an environment variable such as `PYSCOPEGUI_PS2000` or `PYSCOPEGUI_PS2000A`. A library at
either place runs as you, with everything that means. That is the design, not
a flaw in it: somebody who can replace a library in Program Files, or set
your environment, can already run code as you.

What **is** worth reporting:

- a way to run code, or to write outside the settings folder, from a file
  that is meant to be data -- `settings.json`, `layout.json`, or a page of
  the manual;
- a maker's library being loaded from somewhere other than the places named
  above -- the folder pyscopegui was started in, say;
- pyscopegui going online when you did not ask it to. It is designed to go
  online only for *Help > Check for updates*, and for a web page you chose to
  open;
- an instrument's output -- a signal generator -- being switched on without
  your having chosen it. pyscopegui puts back the output you last chose when
  the instrument is run, and is provided without warranty of any kind.

What is **not**, here:

- a script run from the Python Console doing what scripts can. It runs as you,
  with everything that means, and that is what it is for;

- problems in a maker's driver or library, or in the instrument itself.
  Report those to the maker; do tell us if pyscopegui uses one unsafely;
- problems in the libraries pyscopegui is built on -- Qt, pyqtgraph, numpy.
  Report those upstream; do tell us if pyscopegui uses one unsafely.
