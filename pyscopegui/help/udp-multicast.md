[&larr; Contents](manual.md)

# UDP multicast

pyscopegui uses UDP multicast for two things, both with
[pycangui](https://github.com/davhodg/pycangui):

- **decoded CAN sent on**: the frames read off a scope's channel, sent to a group that
  pycangui, or any other python-can program, joins (see [Decoding buses](decoding.md));
- **pycangui's signals received**: the [pycangui signals](pycangui.md) instrument listens for
  the signals pycangui decodes with its database.

A multicast group is a network address that every program which has joined it hears, and
can send to.

## How far it goes

**Tools > Settings > UDP multicast** decides, for both, in both directions. It has the same
three choices as pycangui's own setting of that name:

| Choice | Decoded CAN sent on | pycangui's signals received |
|---|---|---|
| **Off** | Not sent; *Send the frames on to pycangui* is greyed | The instrument does not open; one open is closed |
| **This computer only** (the first time) | Sent to programs on this computer only | Taken from programs on this computer; what another computer sends is dropped |
| **Local network** | Sent to the same network segment | Taken from the same network segment |

- **This computer only** holds both ways. What pyscopegui sends goes with a hop limit of 0,
  which no network adapter passes on. A group can still be heard on every network adapter,
  so signals another computer sends can still arrive: pyscopegui drops them, and the
  [Event Log](event-log.md) names each computer that sent some, once.
- **Local network** goes no further than the network segment: the hop limit is 1, so no
  router passes anything on. Every computer on that segment that has joined a group hears
  the CAN decoded here, and can send signals to the pycangui instrument. Use it on a network
  you trust.
- It is a setting for the computer, not the [workspace](files.md), and it is followed at
  once: frames are sent as it says from the next one, and a pycangui instrument open when it
  is turned off is closed.
- Give pycangui the same choice. Each keeps to its own: with pycangui on the local network
  and pyscopegui on this computer only, pyscopegui still drops what pycangui on another
  computer sends.

### Off, with a bus set to be sent on

A bus can be set to send its frames on while UDP multicast is off -- in a workspace from
another computer, say. Its group is kept, and nothing is sent: *Send the frames on to
pycangui* is greyed in its *Decode as CAN* dialog, still ticked, and the Event Log says once
that its frames are not sent. Choose *This computer only* or *Local network* again, and they
are sent from the next frame, with nothing to tick again.

## Across computers

*Local network* also needs:

- a firewall that lets UDP in, for Python, on each receiving computer: port 43113 for CAN
  frames, 43114 for pycangui's signals;
- a network that carries multicast: a switch usually does, Wi-Fi often badly, and some
  company networks not at all.

Everything goes as UDP, which does not resend what is lost, so on a busy or poor network
some frames or values may not arrive, and none says so. For watching that is usually fine.
