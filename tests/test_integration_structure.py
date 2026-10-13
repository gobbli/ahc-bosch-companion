"""Static checks for the read-only Companion development scaffold.

No Home Assistant runtime is started here. This is NOT an integration test.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "ahc_bosch_companion"


class IntegrationScaffoldTests(unittest.TestCase):
    def test_manifest(self) -> None:
        manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["domain"], "ahc_bosch_companion")
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["version"], "0.1.0-dev1")
        self.assertEqual(manifest["requirements"], [])

    def test_hacs_structure(self) -> None:
        hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
        self.assertEqual(hacs["name"], "AHC Bosch Companion")
        self.assertTrue((COMPONENT / "__init__.py").is_file())
        self.assertTrue((COMPONENT / "sensor.py").is_file())

    def test_translation_json(self) -> None:
        for lang in ("de", "en"):
            with self.subTest(language=lang):
                obj = json.loads(
                    (COMPONENT / "translations" / f"{lang}.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertIn("room_climate", obj["config"]["step"]["user"]["data"])
                self.assertIn(
                    "room_operating_mode", obj["config"]["step"]["user"]["data"]
                )

    def test_all_python_files_parse(self) -> None:
        sources = list(COMPONENT.rglob("*.py"))
        self.assertGreaterEqual(len(sources), 4)
        for path in sources:
            with self.subTest(file=path.name):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_no_heating_actuation(self) -> None:
        """This milestone must be impossible to use as a controller."""
        for path in COMPONENT.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute):
                        self.assertNotIn(
                            node.attr,
                            {"async_call", "async_publish", "async_subscribe",
                             "set_temperature", "set_hvac_mode"},
                        )
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        self.assertNotEqual(node.func.attr, "async_set")
                self.assertNotIn("mqtt.publish", source)

    def test_config_watches_existing_entities(self) -> None:
        flow = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
        sensors = (COMPONENT / "sensor.py").read_text(encoding="utf-8")
        self.assertIn("async_set_unique_id(room_climate)", flow)
        self.assertIn("_abort_if_unique_id_configured()", flow)
        self.assertIn("async_track_state_change_event", sensors)
        self.assertIn("self.async_on_remove(", sensors)


if __name__ == "__main__":
    unittest.main()
