# AHC Bosch Companion

A separate Home Assistant / HACS custom integration for Bosch Room Thermostat II (BTH-RM), Bosch Radiator Thermostat II (BTH-RA), Zigbee2MQTT and the unchanged AHC 5.5.9 blueprint.

**Version 0.1.0b1: supervised pilot only, NOT approved for unattended heating.** The radiator output is OFF after every HA restart or integration reload until explicitly enabled using the Companion safety switch.

## How it works

- AHC controls the virtual climate entity created by this integration, NOT the actual BTH-RA climates.
- The Companion translates the AHC target into Bosch operating_mode=manual and matching setpoint.
- AHC OFF or Bosch room PAUSE translates to the Bosch-specific operating_mode=pause.
- Bosch MANUAL overrides the AHC target. While Bosch is in SCHEDULE, a physical setpoint change temporarily overrides the target until the next on/off edge of ONE configured HA schedule.
- AHC protection event flags (window/frost/liming/forced controls) take priority over local manual changes.
- Supports multiple Bosch radiator climates and their matching operating mode selectors.
- Keeps the existing ten-minute external temperature feeder unchanged; disable AHC calibration for the beta.
- Does not update the room thermostat's display setpoint, and does not support multiple AHC schedules.

## Safety boundaries

A **successful Home Assistant service call is not Zigbee radio confirmation**. Check the real device state after each action. The safety switch OFF does not change valve positions; it simply stops further Companion commands. On restart the valves retain their previous physical state and automatic Companion output stays OFF. Do not operate unattended.

**Do not run a legacy setpoint-sync automation or an AHC instance directly controlling the same physical radiators in parallel with the Companion.**

## Installation and setup

Read the complete German instructions before using:
**[First supervised pilot and rollback](docs/PILOT_DE.md)**.

HACS custom repository URL: https://github.com/gobbli/ahc-bosch-companion (type: Integration). HACS installs from the DEFAULT repository branch, not this development branch. Only install after beta code has been merged.

See [architecture](docs/ARCHITECTURE.md). Original AHC: https://github.com/panhans/HomeAssistant. Bosch Zigbee2MQTT docs: https://www.zigbee2mqtt.io/devices/BTH-RM.html and https://www.zigbee2mqtt.io/devices/BTH-RA.html.

MIT licensed companion code. Not affiliated with Bosch or AHC author.
