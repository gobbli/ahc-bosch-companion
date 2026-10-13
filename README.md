# AHC Bosch Companion

Independent Home Assistant custom integration for **Bosch Room Thermostat II**
and, eventually, **Advanced Heating Control (AHC)**.

> **Status: 0.1.0-dev1 — read-only development preview. NOT a heating controller.**

## Current capabilities

- Installs as a `custom_components/ahc_bosch_companion` integration.
- Configurable through **Settings → Devices & services → Add integration**.
- Choose your existing Zigbee2MQTT Bosch room `climate` entity and its
  `operating_mode` `select` entity.
- Creates two read-only diagnostic sensors:
  - **Operating mode**: `schedule`, `manual`, `pause`
  - **Requested setpoint**: from the room `climate` entity.
- Handles entity updates without polling or publishing device commands.
- Supports multiple room configurations as separate integration entries.

**It does NOT yet** control any radiator thermostat, integrate with AHC,
preserve override modes, send external temperatures, or synchronize the display.
It has only static automated tests; no live Home Assistant runtime validation
or Bosch device testing has been performed.

## Development branch

Work takes place in
[`feature/initial-hacs-integration`](https://github.com/gobbli/ahc-bosch-companion/tree/feature/initial-hacs-integration).
The `master` branch is not used for active development until the code is tested.

## Installation for developers (not production)

This repo is organized for HACS, but **do not install it from HACS yet**:
there is no tested release on the default branch.

For an isolated test instance, copy
`custom_components/ahc_bosch_companion` to
`<config>/custom_components/ahc_bosch_companion`, restart Home Assistant,
and use the integration configuration UI. Remove it if Home Assistant logs an
error. **Do not change any existing heating automation during this test.**

## Architecture, safety rules, and next steps

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

AHC is developed by [panhans](https://github.com/panhans/HomeAssistant).
This companion is a separate project, not affiliated with Bosch or the AHC author.
It contains no copied AHC source code.

## License

MIT, see [LICENSE](LICENSE).
