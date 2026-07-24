from __future__ import annotations

import types
import unittest
from pathlib import Path
from unittest import mock


def load_inference_module() -> types.ModuleType:
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "spark-inference.py"
    source = path.read_text().replace(
        'ROOT = Path("/opt/spark")',
        f"ROOT = Path({str(root)!r})",
        1,
    )
    module = types.ModuleType("spark_inference_recipe_test")
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


class RecipeListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.api = load_inference_module()

    def test_recipe_list_loads_each_recipe_only_once(self) -> None:
        recipes = {
            "prod": {"id": "prod", "lifecycle": self.api.LIFECYCLE_WORKS},
            "testing": {"id": "testing", "lifecycle": self.api.LIFECYCLE_TESTING},
            "draft": {"id": "draft", "lifecycle": self.api.LIFECYCLE_DRAFT},
        }
        with (
            mock.patch.object(self.api, "list_recipe_ids", return_value=list(recipes)),
            mock.patch.object(self.api, "enabled_profiles", return_value=["prod"]) as enabled,
            mock.patch.object(self.api, "load_recipe", side_effect=recipes.__getitem__) as load,
            mock.patch.object(self.api, "recipe_public", side_effect=lambda recipe: dict(recipe)),
        ):
            items = self.api.api_recipe_list()

        self.assertEqual(load.call_count, len(recipes))
        enabled.assert_called_once_with()
        by_id = {item["id"]: item for item in items}
        self.assertTrue(by_id["prod"]["switchable"])
        self.assertTrue(by_id["testing"]["switchable"])
        self.assertFalse(by_id["draft"]["switchable"])


if __name__ == "__main__":
    unittest.main()
