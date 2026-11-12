[&larr; Contents](manual.md)

# Decoding buses

A channel, or a few of one instrument's, can be read as a bus: **CAN**, a **UART** serial
line, **SPI**, **I²C**, or a **parallel** bus. What is read off it is listed in the **Decoded buses** pane, a row
for each frame, burst or transfer, as it arrives.

**Right-click a channel** in the plot's list and choose **Decode as**, then the protocol --
or press **Add...** in the Decoded buses pane and choose the channel there. Once decoded, the
Decoded buses pane opens, with what is read off it. A
bus with more than one line takes the others from the same instrument: its channels are
sampled together, so they line up sample for sample. The channel's menu then offers the
protocol's **decoding...**, to change how it is decoded, and **Stop decoding**. What is
decoded is kept with the [workspace](files.md), and decoded again the next time.

A logic channel is read as it is. An analog one is read as logic at a **threshold**, and has
to go a tenth of a volt past it either way to count as changing, so that noise on a slow edge
is not read as bits. For UART, SPI and I²C the threshold starts at 1.4 V, which suits both
3.3 V and 5 V logic. So does a parallel bus's.

Each bit is read from the samples it spans, so it needs a few of them: three at the very
least, and eight or more to be read reliably. Too few is said in the Decoded buses pane, and
nothing is decoded.

## CAN

Classic CAN, as ISO 11898-1 has it: 11- and 29-bit identifiers, data and remote frames, bit
stuffing, the CRC, and whether a node acknowledged the frame. A CAN FD frame is recognised and
said to be one, but its contents are not read.

| Setting | What it is |
|---------|------------|
| It is | What the channel is on: see below |
| Bit rate | The bus's, or **Found from the signal**: worked out from the shortest pulses, once there are enough of them. One that is not on the list can be typed: `83.333k` |
| Threshold | Where dominant and recessive divide, in volts. Not for a logic level |
| Send the frames on to pycangui | See below |

| It is | Recessive | Dominant | Threshold to start with |
|--------|-----------|----------|-------------------------|
| A logic level: a transceiver's RX or TX, or a logic input | 1 | 0 | -- |
| CAN_H | 2.5 V | 3.5 V | 3.0 V |
| CAN_L | 2.5 V | 1.5 V | 2.0 V |
| CAN_H − CAN_L | 0 V | 2 V | 0.7 V |

On the bus itself, **CAN_H − CAN_L** is the one to use: a probe on each wire, then a
[maths channel](plot.md) of the one less the other, and decode that. It is what a
transceiver reads, and it is far less troubled by noise than either wire alone.

| Bit rate | Samples a second, at least |
|----------|-----------------------------|
| 125 kbit/s | 1 MS/s |
| 250 kbit/s | 2 MS/s |
| 500 kbit/s | 5 MS/s |
| 1 Mbit/s | 10 MS/s |

A PicoScope 2202 to 2205A streams at up to 1 MS/s, enough for 125 kbit/s.

| Problem | What it means |
|---------|---------------|
| *a stuff error: six bits the same* | Six bits in a row the same, which CAN never sends: noise, the wrong bit rate, or another node's error frame |
| *the CRC is wrong* | Read through to the end, but the checksum does not match: a bit read wrong |
| *the CRC delimiter is dominant*, *the ACK delimiter is dominant* | A bit that is always recessive was not |
| *an error frame in the end of frame* | Another node saw something wrong with it, and said so |
| *CAN FD, which is not read* | A CAN FD frame |

Many stuff errors on a bus that works are nearly always the bit rate, or a threshold in the
wrong place: check them before the bus.

### Sending the frames to pycangui

Tick **Send the frames on to pycangui** in the channel's *Decode as CAN* dialog, and each
frame is sent on as it is decoded, by UDP multicast through python-can. pycangui offers the
group **239.74.163.10** as a channel called *pyscopegui*: choose it there, and the frames
read off the scope arrive in its trace like any other bus's, to be decoded with a database,
logged or replayed. Any other python-can program can join the group too:

```python
import can

bus = can.Bus(interface="udp_multicast", channel="239.74.163.10", hop_limit=0)
for msg in bus:
    print(msg)
```

Only good frames are sent, each once, as it is decoded, with the computer's time of its start
of frame. Decoding a channel from what is already held sends nothing: that would arrive as a
burst of the past. A second bus decoded at the same time is best sent to a group of its own,
**239.74.163.11** say, so that pycangui keeps the two apart. The Decoded buses pane says,
beside each bus, where its frames are sent.

**They stay on this computer unless you choose otherwise**, in *Tools > Settings > UDP
multicast*: *This computer only* sends with a hop limit of 0, which keeps them on it, as
pycangui does; *Local network* lets them out onto the network this computer is on, and no
further; *Off* sends nothing, and greys *Send the frames on to pycangui*, keeping the group
for when it is on again. See [UDP multicast](udp-multicast.md).

## UART

A serial line: the debug port of a microcontroller, a GPS's output, RS-232 behind its
transceiver. It rests high; each character is a start bit, its data bits, a parity bit if
there is one, and its stop bits. Each bit is read in its middle, timed from the start bit,
as a UART does: so the baud rate has to be known, to within a few percent.

| Setting | What it is |
|---------|------------|
| Line | The channel |
| Baud | Bits a second. One not on the list can be typed |
| Data bits, Parity, Stop bits | As the line is set: 8, none and 1 is the usual |
| Most significant bit first | Almost never: UARTs send the least significant first |
| Inverted | RS-232 at the connector, between the transceivers, which is the other way up |

Characters that come together -- with no more than a couple of characters' time between any
two -- are one row: in hex, and as text where they are printable, so a line of text reads as
one. Problems: *a framing error* (a stop bit low), *the parity is wrong*, and *a break* (the
line held low).

## SPI

A clock, a data line each way -- **MOSI** from the controller, **MISO** from the device,
either or both -- and a **chip select**, which can be left out.

| Setting | What it is |
|---------|------------|
| Clock, MOSI, MISO, Chip select | The channels: guessed from their names -- SCK, MOSI, MISO, CS -- where they have them |
| Mode | 0 to 3: which way the clock rests, and which edge the data is read on |
| Word | Bits a word: 8, or anything from 1 to 64 |
| Most significant bit first | The usual |
| Chip select active low | The usual |

A transfer is a row: what was sent while the chip select was active, each way, in hex. Without
a chip select, a transfer ends when the clock rests for eight of its bit times. A chip select
released part way through a word is *a word cut short*.

## I²C

**SCL** and **SDA**. A transfer is from a START to the STOP or repeated START after it: a
row, with the device's address -- seven bits or ten -- whether the controller read or wrote,
the bytes, and whether they were acknowledged. *no: nobody there* is an address nobody
answered; a read ends with the controller not acknowledging the last byte, which is how it
says it has had enough, and is no problem.

## Parallel

Several lines read together as one word -- an ADC's outputs, a data bus -- most often on a
mixed-signal scope's logic inputs, D0 to D15. Right-click the bus's first line and choose
**Decode as > Parallel**:

- **First line** and **Width**: the data lines, the first and those after it in the
  instrument's own order -- D0 and 12 lines are D0 to D11. The first is bit 0, the least
  significant, unless it is unticked, when it is the most.
- **Clock**: a word is read at each **rising** edge, **falling** edge, or **both**, as it was
  just before the edge -- what a latch clocked by it would take. With no clock, a word is read
  wherever the lines change and then hold still for the **Settle** time, two samples unless
  it is said: lines that change a little apart, as a bus's do, are not read as a word of
  their own.
- **Multiplex**: a line that says more about each word. A **channel select** says which of
  two channels it is from -- low A, high B, or the other way with **Swap A and B** -- for an
  ADC that sends both its channels on one bus. It may be the clock itself.
- **Enable**: a line that is active while a transfer is sent, low unless it is said.
- **Numbers**: how a word stands for a number -- as it is, offset binary (the middle code
  nought, as many ADCs send), or two's complement.

Words are listed a transfer to a row: what is read while the enable is active, or, without
one, a run of words that a pause ends -- eight of the bus's own word times with nothing read.
A bus that never pauses, an ADC's, is listed 32 words to a row. With a channel select, a
row gives each channel's words together: *A 7FF 801 7FE   B 123 125*.

**Show its words as channels on the plot** draws them as channels of the instrument, each
word held until the next: with a channel select, *Parallel D0 A* and *Parallel D0 B*. Give
the **Full scale** -- an ADC's input span, 2 V peak to peak, say -- and they are in volts;
leave it at nought for the numbers themselves. They are channels like any other: measured,
read by the cursors, triggered on, and made into [maths channels](plot.md) -- A less B, say.

### An AD9238, or an ADC like it

The AD9238 is a dual 12-bit ADC. Multiplexed, it sends both its channels on one set of twelve
lines, a word each half clock, with the clock saying which. Put D0 to D11 on its data lines
and another logic input on its clock, then set **Clock** and **Multiplex** both to that input,
**Read on** to **Both**, and **Numbers** to what the ADC is set to send. If A and B come out
the other way round, tick **Swap A and B**.

Each word is read from the samples it is held for, so the logic inputs want to sample a few
times faster than the words change: a word each half clock is two words a clock. A slower
clock, or a shorter capture at a higher sample rate, suits a first look.

## The Decoded buses pane

Open it from the **View** menu; it opens by itself when a channel is decoded. At its top is
a line for each bus: what it is decoded from and how, and how much has been read from it.

- **Untick** a bus to pause it. What it read is kept, but nothing more is decoded, sent on or
  triggered on, and its rows are left out of the list, until it is ticked again -- when it
  starts afresh from the next samples. A paused bus stays paused with the workspace.
- **Add...** decodes another: choose the channel, then what it carries.
- **Remove** stops decoding the bus chosen, and forgets what it read.

Below, a row for each thing read that started in view on the plot -- or between the two
[cursors](plot.md), when there are two -- every bus's together in the order they came. Zoom
in on a moment and the list is what was read there; zoom out, and it is everything held. The
line above the list says which, how long a stretch that is, and how many were read in it:

| Column | What it is |
|--------|------------|
| Time | When it started, on the plot's time axis |
| Bus | The protocol, and the channels it is read from |
| ID / address | A CAN frame's identifier, in hex -- three figures for an 11-bit one, eight for a 29-bit one -- or an I²C device's address |
| Type | Data or remote and its DLC, for CAN; how many characters or words; read or write |
| Data | What was sent, in hex: a parallel bus's words with as many figures as it is wide |
| ACK | Whether it was acknowledged, for CAN and I²C |
| Problem | What was wrong with it, if anything |

Anything not read cleanly is still listed, in red, with what was wrong. **Click a row** to put
the first [cursor](plot.md) on its start and bring it into view. Select rows and press
**Ctrl+C** to copy them, a tab between the columns, to paste into a spreadsheet. The list
follows the newest as they arrive, unless it has been scrolled up to read; then it stays where
it was put.

To have the plot wait for something in particular -- a frame with an ID, a NACK, a line of
text -- use a **Protocol** [trigger](instruments.md) on the bus.

What was read is kept for as long as the samples it was read from are held: as the
history moves on, the oldest goes with it. Past a point it goes sooner whatever the history,
so that a busy bus cannot fill the computer's memory: half a million frames or messages, or
64 million words of a parallel bus -- about half a minute of an ADC clocked at 1 MHz with a
word on each edge. Each sweep of a Rigol or a Tektronix is decoded on
its own, and what is read from it takes the place of the last sweep's. Samples lost part way
through something, or a capture ending part way through it, is said as its problem.

## Trying it

The demo instrument has a CAN bus on its **CAN** channel, at 10 kbit/s: an engine speed and a
counter, a 29-bit message, and now and then a remote frame. Run it, right-click **CAN**, and
choose **Decode as > CAN...**.
