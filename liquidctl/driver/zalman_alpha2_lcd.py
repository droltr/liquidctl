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

The wire protocol below was recovered from a live USB capture (`usbmon`) of
the real vendor app pushing a background image, not from the native DLL's
named exports (an earlier attempt at decompiling `LcdComm.dll` characterized
a different, apparently unused code path — see `PROTOCOL.md` in the
`zalman-oz-lcd-re` repository for the full history). In short: the panel
receives plain baseline JPEG images (320x320), each preceded by a small
fixed header giving its length, after a short one-time setup sequence.

**Highly experimental / not yet confirmed working end-to-end.** A
byte-for-byte replay of a real captured session (setup sequence + a real
extracted JPEG frame) did not reproduce a visible change on the physical
panel in testing, for reasons not yet understood — see PROTOCOL.md's "MAJOR
REVISION" section for the full writeup and leading theories (most likely: a
USB-level device state that only clears on an actual power cycle, not a
software-only reconnect). Treat this driver as a faithful implementation of
the best current protocol understanding, not as a verified-working driver.

Copyright droltr and contributors
SPDX-License-Identifier: GPL-3.0-or-later
"""

import io
import logging

from PIL import Image

from liquidctl.driver.usb import UsbDriver
from liquidctl.error import NotSupportedByDriver

_LOGGER = logging.getLogger(__name__)

_WRITE_ENDPOINT = 0x02
_DATA_INTERFACE = 1

_LCD_RESOLUTION = (320, 320)

# one-time setup sequence, sent once before the first frame after a
# (re)connect; bytes 3 onward of packets 3 and 4 are replayed verbatim from
# a real capture, their meaning is not yet decoded (see PROTOCOL.md)
_SETUP_PACKET_1 = bytes(16)
_SETUP_PACKET_2 = bytes.fromhex("070300000c0000000000000040014001")
_SETUP_PACKET_3 = bytes.fromhex("0090010200") + bytes(60)
_SETUP_PACKET_4 = bytes.fromhex("023c04b0") + bytes(12)

_FRAME_HEADER_LEN = 16


class ZalmanAlpha2DsLcd(UsbDriver):
    """liquidctl driver for the Zalman ALPHA2 DS LCD screen."""

    _MATCHES = [(0x0483, 0x5740, "Zalman ALPHA2 DS LCD", {})]

    def _select_interface(self, cfg):
        # the LCD's actual data path is the CDC "data" interface (1), not
        # the CDC "communications/control" interface (0)
        return _DATA_INTERFACE

    def initialize(self, **kwargs):
        """Perform the one-time setup sequence.

        Must be called once before the first `set_screen` call after the
        device is (re)connected.
        """

        for packet in (
            _SETUP_PACKET_1,
            _SETUP_PACKET_2,
            _SETUP_PACKET_3,
            _SETUP_PACKET_4,
        ):
            self.device.write(_WRITE_ENDPOINT, packet)
        return []

    def set_screen(self, channel, mode, value, **kwargs):
        """Set the screen content.

        Unstable; see the module docstring.

        Supported channels, modes and values:

        | Channel | Mode     | Value               |
        | ------- | -------- | ------------------- |
        | `lcd`   | `static` | path to image file  |
        """

        assert channel.lower() == "lcd", f"invalid channel, expected 'lcd', got: {channel}"

        if mode == "static":
            jpeg = self._prepare_image(value)
            self._send_frame(jpeg)
            return

        raise NotSupportedByDriver(f"mode not supported: {mode}")

    def _prepare_image(self, path):
        """Load `path`, resize to the panel resolution and JPEG-encode it."""

        img = Image.open(path).resize(_LCD_RESOLUTION).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    def _send_frame(self, jpeg):
        """Upload one JPEG-encoded frame (see PROTOCOL.md)."""

        header = bytearray(_FRAME_HEADER_LEN)
        header[0] = 0x05
        header[4:6] = len(jpeg).to_bytes(2, "little")
        self.device.write(_WRITE_ENDPOINT, bytes(header))
        self.device.write(_WRITE_ENDPOINT, jpeg)
