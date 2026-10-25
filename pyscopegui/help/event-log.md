[&larr; Contents](manual.md)

# Event Log

Everything pyscopegui says goes to the **Event Log** with a level, and the level is what the
line looks like:

- an **error** in red and bold -- something went wrong that nobody asked for: a scope that
  would not open, a library that is missing;
- a **warning** in amber -- what you asked for did not happen, or not as asked: samples that
  were lost, a rate the instrument could not keep to;
- **good news** in green -- something that was wrong is right again;
- anything else in the ordinary text colour, because a colour on every line is a colour that
  says nothing.

The colours follow the theme: one set reads against a pale background, another against a
dark one.

Everything is kept for the whole session -- the line that matters is often the first of a
thousand -- until **Clear**, on the pane's right-click, empties it.

A warning or an error opens the pane if it has been closed; a plain note does not, and
neither does good news. So closing the pane means "stop chattering at me" rather than "hide
failures from me".

An error inside pyscopegui itself -- a bug -- is reported here with its traceback, rather
than disappearing with only a button that did nothing to show for it. Please send it with a
bug report.

*Help > Diagnostics...* opens a report of the versions, the instruments and what they have
sent, and the last warnings and errors here, in a window of its own, and copies it to the
clipboard; see [About, licences and updates](about.md).
