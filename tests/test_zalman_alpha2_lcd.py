"""Adapter tests: the USB discovery handle must never claim the CDC interface."""
import sys
import unittest
from types import ModuleType
from unittest.mock import Mock, patch

from liquidctl.driver.zalman_alpha2_lcd import ZalmanAlpha2DsLcd


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.usb = Mock(bus='usb1', address=6)
        self.client = Mock()
        module = ModuleType('zalman_lcd.client')
        module.LcdClient = Mock(return_value=self.client)
        patch.dict(sys.modules, {'zalman_lcd.client': module}).start()
        self.addCleanup(patch.stopall)
        self.driver = ZalmanAlpha2DsLcd(self.usb, 'Zalman ALPHA2 DS LCD')

    def test_connect_does_not_detach_kernel_driver(self):
        self.assertIs(self.driver.connect(), self.driver)
        self.driver.initialize()
        self.driver.get_status()
        self.usb.open.assert_not_called()
        self.usb.claim.assert_not_called()
        self.assertEqual(self.driver.lcd_resolution, (320, 320))

    def test_static_maps_to_overlay_client(self):
        self.driver.set_screen('lcd', 'static', '/tmp/frame.png')
        self.client.set_image.assert_called_once_with('/tmp/frame.png')
        self.driver.disconnect()
        self.client.close.assert_called_once()
        self.usb.close.assert_not_called()

    def test_unknown_channel_does_not_connect(self):
        with self.assertRaises(ValueError):
            self.driver.set_screen('fan', 'static', '/tmp/frame.png')
        self.assertIsNone(self.driver._lcd)

    def test_brightness_and_orientation_are_forwarded(self):
        self.driver.set_screen('lcd', 'brightness', '70')
        self.driver.set_screen('lcd', 'orientation', '90')
        self.client.set_brightness.assert_called_once_with('70')
        self.client.set_orientation.assert_called_once_with('90')


if __name__ == '__main__':
    unittest.main()
