[&larr; Contents](manual.md)

# Your files

pyscopegui keeps two files of yours in a **workspace**, a folder of its own. Everybody has
one called `default`, and somebody who never makes another need never know it is there.
The workspaces are under:

| System | Folder |
|--------|--------|
| Windows | `%APPDATA%\pyscopegui\workspaces` |
| Linux | `~/.config/pyscopegui/workspaces` |

*File > Workspace > Open folder* opens the one in use.

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
pyscopegui first starts. The two files were kept in the `pyscopegui` folder itself before
there were workspaces; the first time a newer pyscopegui starts, it moves them into
`default`, so everything is as it was left.

## Workspaces

A workspace is everything about what is being measured: the instruments in the
[Instrument](instruments.md) pane, how each is reached and set up, their triggers, what the
plots show, and where the panes are. One for each bench or setup -- the scopes at home, and
the one at work -- means taking the laptop from one to the other is choosing a workspace,
not setting everything up again.

*File > Workspace*:

| Entry | What it does |
|-------|--------------|
| New... | A workspace with nothing in it: the panes as they first open, and the demo |
| Save as... | Everything as it is now, under a new name, and carries on in that |
| Switch to | Opens another workspace |
| Manage... | Renames or deletes one |
| Open folder | Opens the folder of the one in use |

There is no Save: a workspace keeps every change as it is made, as `settings.json` always
has. The title bar names the workspace in use, unless it is `default`.

**Switching closes every instrument that is open**, since the next workspace has
instruments of its own, and the window is opened again on it. If any is open, pyscopegui
asks first. What is on the plot is not kept.

`default` cannot be renamed or deleted, and neither can the workspace in use: switch to
another first. A workspace is a folder, so it can be copied, backed up, or sent to somebody
else with everything in it. Where the window sits and whether it is light or dark stay
with this computer, whichever workspace is open.

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
