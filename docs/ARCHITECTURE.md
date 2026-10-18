# AHC Bosch Companion – beta architecture (0.1.0b3 proposed)

## Components

- `config_flow.py`: Select a BTH-RM room climate, room mode select, measured
  temperature, Zigbee2MQTT room-state topic, ONE Home Assistant schedule,
  one or more BTH-RA climate + operating-mode select pairs. Device Registry
  pairing prevents commands being issued to the wrong TRV. AHC automation
  can be bound later in **Configure**.
- `controller.py`: Read `ahc_event` from exactly the configured AHC
  automation, watch MQTT room change source and selected HA schedule, arbitrate
  physical setpoint changes, schedule boundary resets and safety priorities.
  Device command output initializes OFF. In the proposed b3, an explicitly enabled auto-resume option may reopen it only after new matching AHC data, room MQTT data, both radiator HA state updates, and a 90-second stability period. This does not establish Zigbee command acknowledgements.
- `climate.py`: Expose virtual ClimateEntity. AHC's thermostat list contains
  ONLY this entity; it exposes AHC requested target and room current temp.
  It **must not** expose local manual override as the AHC target.
- `policy.py`: Pure tested rules for schedule/manual/temporary/pause and AHC
  window/frost/liming/forced controls.
- `switch.py`: Explicit authorization for physical commands; turning OFF
  blocks further writes, does **not** issue TRV stop/restore.
- `sensor.py`: Read-only room mode and requested temperature diagnostics.

## Ownership

Normal AHC schedule -> virtual climate -> Companion -> physical Bosch TRVs.
AHC's `ahc_event` conveys window/frost/liming context so local manual target
does not override AHC protection. Bosch radiators require manufacturer
`operating_mode` manual/pause; standard HVAC OFF is not suitable.

Companion does NOT send the external room temperature; the **already working**
10-minute HA automation owns `remote_temperature` for both BTH-RAs until a
future, separately validated integration step. AHC calibration must be OFF.

## Pilot constraints / unsolved

- Only ONE schedule helper, temporary override expires at its on/off edge.
  Consecutive blocks with no state edge, multiple schedules or other AHC
  scheduler logic are not handled.
- No automatic BTH-RM display synchronization.
- No explicit Zigbee command acknowledgement. Automatic resume is proposed as
  a separate opt-in that starts OFF and waits for fresh HA/MQTT reports; a
  physical delivery guarantee or safe unattended operation is NOT provided.
- HA service calls can be accepted despite physical communication failures.
- Only formal manifest tests and isolated policy tests exist; no Bosch hardware
  testing has been performed. **Use with supervision and rollback plan only.**
- This integration is independently authored. No AHC blueprint source code
  is copied. Upstream: https://github.com/panhans/HomeAssistant

Read [PILOT_DE.md](PILOT_DE.md) before testing.
