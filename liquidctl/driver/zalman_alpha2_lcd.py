"""liquidctl driver for the Zalman ALPHA2 DS LCD screen.

Supported devices:

- Zalman ALPHA2 DS A24/A36 (Black/White) — LCD screen only

Driver
------

The ALPHA2 DS AIO exposes its LCD screen as a USB-CDC ("virtual COM port")
device (`0483:5740`, STMicroelectronics-based). This driver talks to it
directly over the raw USB bulk endpoints of the CDC data interface, instead
of going through a kernel tty driver, following the same approach used by
other non-HID devices in liquidctl (see `asetek.py`).

Only the LCD screen is supported. The RGB fans/pump lighting on this AIO are
wired through the motherboard's own ARGB header on the reference test
system, not through this controller, and are out of scope for this driver;
see the `zalman-oz-lcd-re` and `msi-mystic-light-re` research repositories
(https://github.com/droltr) for background.

Protocol
--------

Confirmed two independent ways: a live USB capture (`usbmon`) of the real
vendor app, and — decisively — decompiling every LCD-relevant function of
the native `LcdComm.dll` with Ghidra (not just characterizing named exports
from the outside, as an earlier pass did). See `PROTOCOL.md` in the
`zalman-oz-lcd-re` repository for the full byte-level writeup and revision
history; the short version:

- The panel takes plain baseline JPEG images (320x320), pushed through
  `SetVideoDownload` (session init) -> one `SetDisplayVideo` call per frame
  -> `SetVideoOver` (once, after all frames).
- Critically, **any payload larger than one USB packet is sent as fixed
  64-byte, zero-padded chunks, followed by an explicit standalone 1-byte
  `0x00` write marking end-of-transfer** — confirmed directly from
  `LcdComm.dll`'s internal chunking helper (`FUN_18000340c` in the Ghidra
  decompilation). Every prior replay attempt (including earlier versions of
  this very driver) sent the JPEG payload as one large write with no
  chunking and no trailing terminator byte, which is the most likely reason
  none of them ever rendered anything on the physical panel despite
  otherwise-correct bytes.
- The earlier "one-time setup sequence" of 4 writes seen in usbmon captures
  was a **misreading of unrelated, concurrently-running traffic**, not an
  actual prerequisite for playing a theme: packet 1 (16 zero bytes) is a
  `BreatheSignel` keepalive the real app's background thread sends every
  second regardless of what else is happening; packet 2 (`07 03 00 00 0c
  00 00 00 00 00 00 00 40 01 40 01`) is a `SetDisplayInfo` header (the live
  sensor-overlay push, also on that same background thread) — sent
  *without* its corresponding payload in the old capture-derived replay,
  which very likely desynced the device's receive state machine before the
  theme push that followed ever had a chance to work. Neither is required
  to play a theme, and this driver no longer sends them.

Copyright droltr and contributors
SPDX-License-Identifier: GPL-3.0-or-later
"""

import io
import logging

from PIL import Image, ImageColor

from liquidctl.driver.usb import UsbDriver
from liquidctl.error import NotSupportedByDriver

_LOGGER = logging.getLogger(__name__)

_WRITE_ENDPOINT = 0x02
_DATA_INTERFACE = 1

_LCD_RESOLUTION = (320, 320)
_CHUNK_SIZE = 64
_FRAME_HEADER_LEN = 16


class ZalmanAlpha2DsLcd(UsbDriver):
    """liquidctl driver for the Zalman ALPHA2 DS LCD screen."""

    _MATCHES = [(0x0483, 0x5740, "Zalman ALPHA2 DS LCD", {})]

    def _select_interface(self, cfg):
        # the LCD's actual data path is the CDC "data" interface (1), not
        # the CDC "communications/control" interface (0)
        return _DATA_INTERFACE

    def initialize(self, **kwargs):
        """No-op.

        Earlier versions of this driver replayed a captured "one-time setup
        sequence" here; that sequence is now understood to be unrelated
        background traffic, not a real prerequisite — see the module
        docstring. `SetVideoDownload`/`SetDisplayVideo`/`SetVideoOver` (see
        `set_screen`) are the complete, self-sufficient sequence.
        """
        return []

    def set_screen(self, channel, mode, value, **kwargs):
        """Set the screen content.

        Supported channels, modes and values:

        | Channel | Mode     | Value                                |
        | ------- | -------- | ------------------------------------ |
        | `lcd`   | `static` | path to an image file                |
        | `lcd`   | `color`  | a solid color: "RRGGBB" or a name    |
        """

        assert channel.lower() == "lcd", f"invalid channel, expected 'lcd', got: {channel}"

        if mode == "static":
            jpeg = self._prepare_image(value)
        elif mode == "color":
            jpeg = self._prepare_color(value)
        else:
            raise NotSupportedByDriver(f"mode not supported: {mode}")

        self._send_video_download(frame_rate=1, frame_qty=1)
        self._send_frame(jpeg)
        self._send_video_over()
        return []

    def _prepare_image(self, path):
        """Load `path`, resize to the panel resolution and JPEG-encode it."""

        img = Image.open(path).resize(_LCD_RESOLUTION).convert("RGB")
        return self._encode_jpeg(img)

    def _prepare_color(self, color):
        """Build a solid-color frame, JPEG-encoded."""

        rgb = ImageColor.getrgb(color if color.startswith("#") else f"#{color}")
        img = Image.new("RGB", _LCD_RESOLUTION, rgb)
        return self._encode_jpeg(img)

    def _encode_jpeg(self, img):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    def _send_video_download(self, frame_rate, frame_qty):
        """`SetVideoDownload` — session init, once before any frame.

        Wire format: byte 0 = 0x02 (opcode), byte 1 = frameRate, bytes 2-3 =
        frameQty as big-endian uint16, rest zero. A single 16-byte write,
        confirmed from `LcdComm.dll`'s decompiled body.
        """

        packet = bytearray(_FRAME_HEADER_LEN)
        packet[0] = 0x02
        packet[1] = frame_rate & 0xFF
        packet[2:4] = frame_qty.to_bytes(2, "big")
        self.device.write(_WRITE_ENDPOINT, bytes(packet))

    def _send_frame(self, jpeg):
        """`SetDisplayVideo` — one call per frame, in order.

        A 16-byte header (opcode 0x05, JPEG length as little-endian uint32
        at bytes 4-7, rest zero), sent as a single write, followed by the
        JPEG bytes sent through `_write_chunked` (see below).
        """

        header = bytearray(_FRAME_HEADER_LEN)
        header[0] = 0x05
        header[4:8] = len(jpeg).to_bytes(4, "little")
        self.device.write(_WRITE_ENDPOINT, bytes(header))
        self._write_chunked(jpeg)

    def _send_video_over(self):
        """`SetVideoOver` — once, after all frames have been sent."""

        self.device.write(_WRITE_ENDPOINT, bytes([0x06]) + bytes(15))

    def _write_chunked(self, payload):
        """Send `payload` the way `LcdComm.dll` actually does it internally
        (`FUN_18000340c` in the Ghidra decompilation): fixed 64-byte,
        zero-padded chunks, one bulk write per chunk, followed by a
        standalone single zero-byte write marking end-of-transfer.

        This trailing terminator is not optional — see the module
        docstring.
        """

        for offset in range(0, len(payload), _CHUNK_SIZE):
            chunk = payload[offset : offset + _CHUNK_SIZE]
            if len(chunk) < _CHUNK_SIZE:
                chunk = chunk + bytes(_CHUNK_SIZE - len(chunk))
            self.device.write(_WRITE_ENDPOINT, chunk)
        self.device.write(_WRITE_ENDPOINT, b"\x00")
