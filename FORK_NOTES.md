# Fork notes

This repository is a copy of [liquidctl/liquidctl](https://github.com/liquidctl/liquidctl).
`main` tracks upstream unchanged. All fork-specific work lives on the
`zalman-alpha2-ds-lcd` branch and is summarized here.

## What this fork adds

An experimental driver for the **Zalman ALPHA2 DS LCD** screen (USB `0483:5740`,
enumerates as a USB-CDC virtual COM port).

| File | Change |
|---|---|
| `liquidctl/driver/zalman_alpha2_lcd.py` | New `ZalmanAlpha2DsLcd` driver (thin adapter) |
| `liquidctl/driver/__init__.py` | Registers the new driver module |
| `setup.cfg` | Adds the optional `zalman` extra (`zalman-lcd>=0.2.0`) |
| `tests/test_zalman_alpha2_lcd.py` | Mock-based adapter tests (no hardware access) |

### Design

- USB is used only for discovery and identity. The driver does **not** call
  `UsbDriver.connect()`, so the kernel `cdc_acm` driver stays attached.
- The LCD protocol itself is implemented by the `zalman-lcd` package from
  [droltr/zalman-Alpha2-DS-LCD-Linux](https://github.com/droltr/zalman-Alpha2-DS-LCD-Linux)
  (MIT license). The driver forwards `set_screen` calls to
  `zalman_lcd.client.LcdClient`.
- Supported `set_screen` modes on channel `lcd`: `static` (image file), `color`,
  `brightness`, `orientation`. `initialize` and `get_status` return no data.
- Fan and pump control are not part of this driver.

### Installation

`zalman-lcd` is not published on PyPI, so install it from its repository first:

```bash
pip install "git+https://github.com/droltr/zalman-Alpha2-DS-LCD-Linux"
pip install -e .
```

Without `zalman-lcd`, the device is still discovered, but LCD commands raise
`NotSupportedByDriver`.

### Usage

```bash
liquidctl --match "Zalman ALPHA2" set lcd screen static /path/to/image.png
liquidctl --match "Zalman ALPHA2" set lcd screen brightness 70
```

## Status

> **⚠️ UNVERIFIED:** End-to-end rendering on the physical panel through this
> liquidctl driver has not been confirmed. The automated tests mock `LcdClient`
> and do not touch hardware.
> To verify: with the panel connected, run a `color` or `static` command and
> check the screen visually.

## History notes

The first two commits on the branch (`ee55dfd`, `d39e605`) contain a from-scratch
protocol implementation that never rendered on the panel; their messages refer to
an earlier research repository. Commit `331ed8d` replaced that code with the
adapter described above. Those older commit messages are kept as history and no
longer describe the current code.

## Upstream status

No pull request has been opened against upstream liquidctl.
