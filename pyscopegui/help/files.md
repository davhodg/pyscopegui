[&larr; Contents](manual.md)

# Your files

pyscopegui keeps two files of yours, in one folder:

| System | Folder |
|--------|--------|
| Windows | `%APPDATA%\pyscopegui` |
| Linux | `~/.config/pyscopegui` |

*Tools > Open settings folder* opens it.

- **`settings.json`** --- what you chose: the instrument, its settings, how much history is
  kept, which channels each plot shows, how long a stretch of time Follow keeps in view. It is plain text with one key
  to a line, so it can be read, edited by hand or kept in version control. Anything in it
  that pyscopegui cannot make sense of is treated as not being there, so a mistake made by
  hand costs that one setting and nothing else.
- **`layout.json`** --- where the panes are. Nobody is meant to read this one.

Where the window sits on the screen, and whether it is light or dark, are kept by the system
for you on this computer rather than in the folder: copying the folder to another machine
should not move the window to where a different monitor was.

Upgrading and uninstalling leave the folder alone. Deleting it puts everything back to how
pyscopegui first starts.

## An instrument's settings

Each instrument's settings are one entry in `settings.json`, named for the instrument. The
[Instrument](instruments.md) pane writes it, and it can be written by hand as well:

```json
"instrument.picoscope2000": {
  "rate": 500000,
  "range_a": "5V"
}
```

What is left out is the default.

A second instrument of the same kind is named with a number, and has an entry of its own:
`"instrument.rigol1000z#2"`. Which instruments are in the pane is the list
`"instruments.added"`, and the one chosen is `"instrument.name"`.

## What is not kept

The samples. What is on the plot is held in memory while pyscopegui is open, and is gone
when it closes or when the instrument is started again.
