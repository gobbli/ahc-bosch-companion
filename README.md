# AHC Bosch Companion

A separate Home Assistant / HACS custom integration for Bosch Room Thermostat II (BTH-RM), Bosch Radiator Thermostat II (BTH-RA), Zigbee2MQTT and the unchanged AHC 5.5.9 blueprint.

**Version 0.1.0b3 (proposed): supervised pilot only, NOT approved for unattended heating.** The radiator output starts OFF after every HA restart or integration reload. Manual enabling remains the default; a separate, experimental auto-resume opt-in can be enabled in Configure. It only releases output after fresh AHC, room MQTT and both radiator HA updates plus 90 seconds of stable readiness. **HA updates are not Zigbee delivery/availability proofs.**

## How it works

- AHC controls the virtual climate entity created by this integration, NOT the actual BTH-RA climates.
- The Companion translates the AHC target into Bosch operating_mode=manual and matching setpoint.
- AHC OFF or Bosch room PAUSE translates to the Bosch-specific operating_mode=pause.
- Bosch MANUAL overrides the AHC target. While Bosch is in SCHEDULE, a physical setpoint change temporarily overrides the target until the next on/off edge of ONE configured HA schedule.
- AHC protection event flags (window/frost/liming/forced controls) take priority over local manual changes.
- Supports multiple Bosch radiator climates and their matching operating mode selectors.
- Keeps the existing ten-minute external temperature feeder unchanged; disable AHC calibration for the beta.
- Does not update the room thermostat's display setpoint, and does not support multiple AHC schedules.

## Proposed change in 0.1.0b3 (guarded automatic restart)

- Separate opt-in `auto_resume` option; OFF by default. The previous manual-enable behavior is unchanged unless explicitly enabled.
- Wait for one new event from the configured AHC automation, a non-retained room MQTT setpoint message, post-start updates from the room temperature sensor and both radiator climate entities, and 90 seconds of stable valid inputs. Status diagnostics are exposed as virtual-climate attributes.
- Suppress new actuator commands when auto-resume has been configured but HA temperature/radiator updates are older than 15 minutes. Manually setting the output switch OFF cancels pending auto-resume for the current integration runtime.
- This is NOT a Zigbee-acknowledged fail-safe. Real hardware startup, disconnect, heating safety, and recovery tests remain mandatory. Do not enable unattended heating based on mock tests.

## Changes in 0.1.0b2 (schedule/race hardening)

- A schedule on/off edge suspends radiator commands until a new valid AHC event is received. This prevents a temporary manual override from reverting to the OLD comfort/eco target before AHC recalculates. If AHC never emits a valid event, the controller deliberately waits rather than issuing a stale target.
- Commands that are superseded by a later AHC, room-mode, or physical override change are not continued to the next device/service operation.
- The old unconditional 90-second suppression is replaced by state-aware verification and a 25-second cooldown. After requested changes, the integration checks both valves again. If a HA-reported mode/temperature disagrees, it retries; a service call is still not a Zigbee delivery guarantee.
- Home Assistant INFO logs document outgoing mode/temperature requests and schedule-boundary waits. No unattended use yet: window/frost/liming, device reconnection and long-term stability still require actual testing.

## Safety boundaries

A **successful Home Assistant service call is not Zigbee radio confirmation**. Check the real device state after each action. The safety switch OFF does not change valve positions; it simply stops further Companion commands. On restart the valves retain their previous physical state. Output starts OFF; it can auto-enable only after explicit opt-in and readiness checks. A blocked output does not stop a valve already heating. Do not operate unattended.

**Do not run a legacy setpoint-sync automation or an AHC instance directly controlling the same physical radiators in parallel with the Companion.**

## Installation and setup

Read the complete German instructions before using:
**[First supervised pilot and rollback](docs/PILOT_DE.md)**.

HACS custom repository URL: https://github.com/gobbli/ahc-bosch-companion (type: Integration). HACS installs from the DEFAULT repository branch, not this development branch. Only install after beta code has been merged.

See [architecture](docs/ARCHITECTURE.md). Original AHC: https://github.com/panhans/HomeAssistant. Bosch Zigbee2MQTT docs: https://www.zigbee2mqtt.io/devices/BTH-RM.html and https://www.zigbee2mqtt.io/devices/BTH-RA.html.

MIT licensed companion code. Not affiliated with Bosch or AHC author.
