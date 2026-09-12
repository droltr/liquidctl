"""Zalman ALPHA2 DS LCD adapter for the optional zalman-lcd library.

USB is used only for discovery/identity. The library owns the cdc_acm serial
connection and implements the verified LCD protocol. Fan and pump control
remain with their separate motherboard/controller drivers.

Copyright droltr and contributors
SPDX-License-Identifier: GPL-3.0-or-later
"""

from liquidctl.driver.usb import UsbDriver
from liquidctl.error import NotSupportedByDriver


class ZalmanAlpha2DsLcd(UsbDriver):
    """Linux CDC display, with static dashboard updates through its overlay."""

    _MATCHES = [(0x0483, 0x5740, "Zalman ALPHA2 DS LCD", {})]

    def __init__(self, device, description, **kwargs):
        super().__init__(device, description, **kwargs)
        self.lcd_resolution = (320, 320)
        self._lcd = None

    def connect(self, **kwargs):
        # Do NOT call UsbDriver.connect(): it detaches cdc_acm from the device.
        # Opening the serial port is deferred until the first LCD command, so a
        # missing/busy display cannot prevent discovery of other cooling devices.
        if self._lcd is None:
            try:
                from zalman_lcd.client import LcdClient
            except ImportError as e:
                raise NotSupportedByDriver(
                    "Zalman LCD requires the zalman-lcd integration package"
                ) from e
            self._lcd = LcdClient(bus=self.bus, address=self.address)
        return self

    def disconnect(self, **kwargs):
        if self._lcd is not None:
            self._lcd.close()
            self._lcd = None

    def initialize(self, **kwargs):
        return []

    def get_status(self, **kwargs):
        return []

    def set_screen(self, channel, mode, value, **kwargs):
        if channel.lower() != "lcd":
            raise ValueError("Expected the lcd channel")
        if mode not in ("static", "color", "brightness", "orientation"):
            raise NotSupportedByDriver(f"mode not supported: {mode}")
        if self._lcd is None:
            self.connect()
        if mode == "static":
            self._lcd.set_image(value)
        elif mode == "color":
            self._lcd.set_color(value)
        elif mode == "brightness":
            self._lcd.set_brightness(value)
        elif mode == "orientation":
            self._lcd.set_orientation(value)
        return []
