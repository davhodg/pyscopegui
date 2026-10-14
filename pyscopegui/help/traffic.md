[&larr; Contents](manual.md)

# Instrument traffic

The **Instrument traffic** pane shows everything said to an instrument and back: each command
pyscopegui sends, each answer and how long it took to come, and each call into a maker's
library and what it returned. It is for finding out why an instrument is slow, or will not
do what it is told, and for attaching to a bug report.

Open it from the **View** menu. It opens behind the [Event Log](event-log.md).

## Only while it is open

**Nothing is kept while the pane is not on screen.** Recording starts when it is opened and
stops when it is put away, and while it is stopped the instruments pay nothing for it. It is
put away again every time pyscopegui starts, whatever it was left as, so that it is never
recording without somebody having asked.

What is shown stays until **Clear**, or until pyscopegui is closed. The newest ten thousand
lines are kept on screen.

## Reading it

```
14:03:05.123  Tektronix COM7         -> CH2:SCALE 2
14:03:05.125  Tektronix COM7         -> *OPC?
14:03:05.940  Tektronix COM7         <- 1   (815 ms)
14:03:07.201  Tektronix COM7         <- 2,500 bytes   (1312 ms)
14:03:07.300  PicoScope                 ps2000_ready(1) -> 1   (0 ms)   x37
```

- The time, by the computer's clock, to the millisecond.
- Which instrument, as it is reached: *Rigol 192.168.1.13*, *Rigol USB*, *Tektronix COM7*,
  *PicoScope*.
- **->** is sent to the instrument, **<-** came back from it, and a line with neither is a call
  into the maker's library, with what it returned.
- In brackets, how long an answer or a call took. A setting the scope took a second over is
  plain to see.
- **x37** is the same line, thirty-seven times running: a scope's library is asked whether it
  has anything a hundred times a second, and each of those on a line of its own would bury
  everything else.

A waveform or a block of memory is given as how many bytes came, not the bytes themselves.

## The buttons

| Button | What it does |
|--------|--------------|
| Show | Every instrument, or one of them |
| Pause | Stops adding lines, to read what is there. What arrives meanwhile is shown after |
| Clear | Throws away what is shown |
| Copy | Copies what is shown, to paste somewhere else |
| Save... | Writes what is shown to a text file |

A saved file has the addresses and ports of your instruments in it, and their serial numbers
where they were asked for. Look over it before sending it to anybody.
