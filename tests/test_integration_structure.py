"""Static structure checks: runtime hardware tests are required before release."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "ahc_bosch_companion"


class IntegrationScaffoldTests(unittest.TestCase):
    def test_manifest(self):
        m = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["domain"], "ahc_bosch_companion")
        self.assertTrue(m["config_flow"])
        self.assertEqual(m["version"], "0.1.0b3")
        self.assertIn("mqtt", m["dependencies"])

    def test_hacs_structure(self):
        m = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        self.assertEqual(m["name"], "AHC Bosch Companion")
        for file in ("__init__.py", "climate.py", "config_flow.py", "controller.py",
                     "policy.py", "sensor.py", "switch.py"):
            self.assertTrue((COMPONENT / file).is_file(), file)

    def test_translations(self):
        fields = {"room_climate", "room_operating_mode", "room_temperature",
                  "room_mqtt_topic", "ahc_automation", "schedule_entity",
                  "radiator_climates", "radiator_modes"}
        for lang in ("de", "en"):
            content = json.loads((COMPONENT / "translations" / f"{lang}.json").read_text())
            self.assertEqual(set(content["config"]["step"]["user"]["data"]), fields)

    def test_python_syntax(self):
        for path in COMPONENT.rglob("*.py"):
            with self.subTest(file=path.name):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_output_gated_and_restart_off(self):
        control = (COMPONENT / "controller.py").read_text(encoding="utf-8")
        self.assertIn("self.enabled = False", control)
        self.assertIn("if not self.enabled:", control)
        self.assertIn("if not self.device_ready:", control)
        self.assertIn("if not self.ahc_seen", control)
        self.assertIn('self.hass.bus.async_listen("ahc_event"', control)
        self.assertIn('if event.data.get("automation") != self.data.get(CONF_AHC_AUTOMATION):', control)
        self.assertIn("if getattr(message, \"retain\", False):", control)
        self.assertIn("is_physical_schedule_change(", control)

    def test_trv_pairing_checked_by_device_registry(self):
        flow = (COMPONENT / "config_flow.py").read_text()
        self.assertIn("c.device_id != m.device_id", flow)
        self.assertIn('{"manual", "pause"}', flow)


if __name__ == "__main__":
    unittest.main()
