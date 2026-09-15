"""CPython tests for the website-provided ``courser`` teaching helpers."""

import importlib.util
import json
import pathlib
import runpy
import sys
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).parents[1] / "static" / "python" / "courser.py"
MAZE_PATH = pathlib.Path(__file__).parents[1] / "docs" / "examples" / "interactive_maze.py"


def load_courser():
    name = "courser_library_test_module"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CourserLibraryTests(unittest.TestCase):
    def setUp(self):
        self.courser = load_courser()
        self.events = []
        self.courser._configure(self.events.append)

    def event(self, index=-1):
        return json.loads(self.events[index])

    def test_display_snapshots_scalars_lists_and_ragged_lists(self):
        value = [1, "hi", [True, None, 2.5], []]
        self.assertIsNone(self.courser.display(value))
        value[0] = 99

        event = self.event()
        self.assertEqual(event["type"], "display")
        self.assertIsNone(event["label"])
        self.assertEqual(event["value"]["items"][0], {
            "kind": "scalar", "text": "1", "key": "int:1"
        })
        self.assertEqual(event["value"]["items"][1], {
            "kind": "scalar", "text": "'hi'", "key": "str:'hi'"
        })
        self.assertEqual(event["value"]["items"][2]["items"][0]["key"], "bool:True")
        self.assertEqual(event["value"]["items"][2]["items"][1]["text"], "None")
        self.assertEqual(event["value"]["items"][3], {"kind": "list", "items": []})

    def test_independent_labels_replace_their_own_slots(self):
        self.courser.display(1, "score")
        self.courser.display(2, "score")
        self.courser.display(3, "lives")
        self.courser.display(4)

        self.assertEqual([self.event(i)["label"] for i in range(4)], [
            "score", "score", "lives", None,
        ])
        for index in range(5, 22):
            self.courser.display(index, "slot-{}".format(index))
        with self.assertRaisesRegex(ValueError, "20 independent display labels"):
            self.courser.display(22, "one-too-many")

    def test_map_uses_user_defined_type_distinct_symbols_and_snapshots(self):
        self.courser.define_symbol(1, "wall")
        self.courser.define_symbol(True, "open")
        self.courser.define_symbol("1", "text-one")
        grid = [[1, True], ["1", None]]
        self.assertIsNone(self.courser.display_map(grid))
        first_map = self.event()
        self.courser.define_symbol(1, "changed")

        self.assertEqual(first_map["type"], "map")
        self.assertEqual(first_map["symbols"], [
            {"key": "int:1", "text": "wall"},
            {"key": "bool:True", "text": "open"},
            {"key": "str:'1'", "text": "text-one"},
        ])
        self.assertEqual(
            first_map["value"]["items"][1]["items"][0]["key"], "str:'1'"
        )
        self.courser.display_map(grid)
        self.assertEqual(self.event()["symbols"][0]["text"], "changed")

    def test_configure_resets_labels_symbols_and_disabled_mode_is_silent(self):
        self.courser.define_symbol(7, "seven")
        self.courser.display("first", "message")
        self.courser._configure(self.events.append, enabled=False)
        self.courser.display("second", "message")
        self.courser.display_map([[7]])

        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.event()["value"]["text"], "'first'")
        self.courser._configure(self.events.append)
        self.courser.display_map([[7]])
        self.assertEqual(self.event()["symbols"], [])

    def test_validation_catches_unsupported_circular_and_invalid_maps(self):
        with self.assertRaisesRegex(TypeError, r"display value\[1\]"):
            self.courser.display([1, {"not": "supported"}])
        with self.assertRaisesRegex(ValueError, "finite float"):
            self.courser.display(float("nan"))
        with self.assertRaisesRegex(ValueError, "nested more than 2"):
            self.courser.display([[[1]]])
        circular = []
        circular.append(circular)
        with self.assertRaisesRegex(TypeError, "circular list"):
            self.courser.display(circular)
        with self.assertRaisesRegex(ValueError, "rectangular"):
            self.courser.display_map([[1], [2, 3]])
        with self.assertRaisesRegex(TypeError, r"map grid\[0\]\[0\]"):
            self.courser.display_map([[object()]])
        with self.assertRaisesRegex(ValueError, "more than 2500 scalar cells"):
            self.courser.display([[0] * 1251, [0] * 1250])
        with self.assertRaisesRegex(ValueError, "more than 2500 entries"):
            self.courser.display([0] * 2501)
        with self.assertRaisesRegex(ValueError, r"display value\[0\] has more than 2500 entries"):
            self.courser.display([[0] * 2501])
        with self.assertRaisesRegex(ValueError, "more than 100 rows"):
            self.courser.display_map([[0] for _ in range(101)])
        with self.assertRaisesRegex(ValueError, "more than 100 columns"):
            self.courser.display_map([list(range(101))])

    def test_public_surface_and_symbol_limits(self):
        self.assertEqual(self.courser.__all__, ["display", "display_map", "define_symbol"])
        with self.assertRaisesRegex(ValueError, "symbol must not be empty"):
            self.courser.define_symbol(1, "")
        with self.assertRaisesRegex(ValueError, "maximum 500"):
            self.courser.display("x" * 501)
        with self.assertRaisesRegex(ValueError, "maximum 60"):
            self.courser.display(1, "x" * 61)
        for value in range(100):
            self.courser.define_symbol(value, str(value))
        with self.assertRaisesRegex(ValueError, "at most 100 symbol mappings"):
            self.courser.define_symbol(100, "overflow")

    def test_maze_win_refreshes_the_map_at_the_exit(self):
        previous_courser = sys.modules.get("courser")
        sys.modules["courser"] = self.courser
        try:
            with mock.patch("builtins.input", side_effect=[
                "d", "s", "s", "d", "d", "w", "w", "d",
            ]):
                runpy.run_path(MAZE_PATH, run_name="__main__")
        finally:
            if previous_courser is None:
                sys.modules.pop("courser", None)
            else:
                sys.modules["courser"] = previous_courser

        maps = [self.event(index) for index in range(len(self.events))
                if self.event(index)["type"] == "map"]
        self.assertEqual(maps[-1]["value"]["items"][1]["items"][5]["key"], "int:3")
        self.assertEqual(maps[-1]["symbols"], [
            {"key": "int:1", "text": "🧱"},
            {"key": "int:0", "text": "·"},
            {"key": "int:2", "text": "🏁"},
            {"key": "int:3", "text": "🙂"},
        ])


if __name__ == "__main__":
    unittest.main()
