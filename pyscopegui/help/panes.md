[&larr; Contents](manual.md)

# Panes and layout

pyscopegui opens with three panes: the **Instrument** pane beside **Channels and Plot**, and
the **Event Log** underneath. Turn any of them off or on in the **View** menu, and
*View > Reset layout* puts everything back.

If an update changes the set of panes, the saved arrangement cannot be restored --
pyscopegui says so in the [Event Log](event-log.md) -- and the window opens as it first did.

Panes are dockable, so drag them where you like: the arrangement is remembered.

Drag a pane out of the window, or double-click its title bar, and it floats. Hold **Ctrl**
while dragging one, or it will dock again at the first opportunity -- the main window is
looking for somewhere to put it the whole time. Drag it back to dock it, or use
*View > Dock all panes*.

A pane that is out grows two buttons at its top right, and loses them again when it goes
back. Each says what pressing it will do, so **Pin** becomes **Unpin** and **Detach** becomes
**Attach**; hover for what they mean.

Pinning keeps a pane above every other window, pyscopegui's and everyone else's -- except
while pyscopegui is asking a question, when a pinned pane stands down so the dialog can be
seen and answered. Detaching takes it out of its dock altogether, into a window with no
parent: nothing then tries to dock it, it gets a taskbar entry of its own, and it can be sent
to another display and left there. Attaching puts it back where it came from, while closing
that window closes the pane, as closing a docked one does, and *View* shows it again.

The *View* menu ticks every pane that is on screen, a detached one included. Picking a pane
that is out in a window of its own brings that window to the front and leaves it open;
picking a docked one puts it away, and picking it again brings it back.

Which panes are out on their own, and which are pinned, are remembered like the rest of the
settings: a pane left on a second monitor is still there next time.

## More than one plot

*View > Standard panes > Additional Channels and Plot* opens a second
[**Channels and Plot**](plot.md), numbered after the first. Each has settings of its own --
which channels it shows, its own stretch of time, its own voltage axis -- all remembered
separately. The whole capture in one and a few milliseconds of it in the other is what this
is for.

A pane you open arrives **in its own window**, in front of the main one, rather than
squeezing into the space the panes already on screen were using. Drag it into the main window
to dock it, or onto another pane to tab the two together; wherever you leave it is where it
opens next time.

*View > Rename pane* calls one whatever the job calls it. An empty name puts the default
back. Only the label changes -- what identifies a pane to the saved layout is untouched, so
renaming one cannot cost you the arrangement you were renaming.

Closing one puts it away and *View* brings it back. *View > Remove pane* is the other thing:
it closes one for good and forgets it. The first pane of each sort cannot be removed -- that
one is the pane.

## Light or dark

pyscopegui follows the operating system's light or dark setting. *Tools > Settings > Theme*
overrides it -- **Light** or **Dark** -- and **Match the system** hands it back. The plots
follow it too. On Windows 10 and earlier the native style can only be light, so pyscopegui
uses Qt's own Fusion style there, light and dark alike. The change is immediate, and the
choice is kept for you on this computer.
