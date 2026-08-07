"""Tests for the decision logic.

No Frappe, no network, no site — runnable in a second, anywhere:

    python -m unittest discover -s fuse_manufacturing/tests

Every case here is one that actually went wrong during the build. That is deliberate:
these are regression tests, not coverage for its own sake.
"""

import unittest

from fuse_manufacturing import rules


class TestRecipeSignature(unittest.TestCase):
	def test_same_recipe_same_signature(self):
		lines = [{"item_code": "RMNR20", "qty": 0.3021, "uom": "Kilograms"}]
		self.assertEqual(rules.recipe_signature(lines), rules.recipe_signature(lines))

	def test_line_order_is_not_a_change(self):
		"""Intacct can return the same recipe in a different order. That is not a change.

		Without this, a reordered read would cancel and rebuild 900 BOMs for nothing.
		"""
		a = [
			{"item_code": "RMNR20", "qty": 0.3021, "uom": "Kilograms"},
			{"item_code": "RMZNO", "qty": 0.0302, "uom": "Kilograms"},
		]
		b = list(reversed(a))
		self.assertEqual(rules.recipe_signature(a), rules.recipe_signature(b))

	def test_quantity_change_is_detected(self):
		a = [{"item_code": "RMNR20", "qty": 0.3021, "uom": "Kilograms"}]
		b = [{"item_code": "RMNR20", "qty": 0.3022, "uom": "Kilograms"}]
		self.assertNotEqual(rules.recipe_signature(a), rules.recipe_signature(b))

	def test_trailing_zeros_are_not_a_change(self):
		a = [{"item_code": "X", "qty": 0.0085, "uom": "Kilograms"}]
		b = [{"item_code": "X", "qty": 0.00850000, "uom": "Kilograms"}]
		self.assertEqual(rules.recipe_signature(a), rules.recipe_signature(b))

	def test_unit_change_is_detected(self):
		a = [{"item_code": "X", "qty": 1, "uom": "Kilograms"}]
		b = [{"item_code": "X", "qty": 1, "uom": "Litres"}]
		self.assertNotEqual(rules.recipe_signature(a), rules.recipe_signature(b))


class TestControlId(unittest.TestCase):
	def test_deterministic(self):
		"""The whole point: a retry must carry the same control ID or it double-posts."""
		self.assertEqual(
			rules.control_id_for("Stock Entry", "MAT-STE-0001", "manufacture"),
			rules.control_id_for("Stock Entry", "MAT-STE-0001", "manufacture"),
		)

	def test_different_documents_differ(self):
		self.assertNotEqual(
			rules.control_id_for("Stock Entry", "MAT-STE-0001"),
			rules.control_id_for("Stock Entry", "MAT-STE-0002"),
		)

	def test_purpose_distinguishes_legs(self):
		self.assertNotEqual(
			rules.control_id_for("Stock Entry", "X", "consume"),
			rules.control_id_for("Stock Entry", "X", "produce"),
		)


class TestPrecision(unittest.TestCase):
	def test_raises_to_intacct(self):
		self.assertEqual(
			rules.decide_precision(["4", "4", "2"], current=3), {"action": "raise", "from": 3, "to": 4}
		)

	def test_never_lowers(self):
		"""Lowering would silently round every quantity already stored."""
		result = rules.decide_precision(["2"], current=4)
		self.assertEqual(result["action"], "warn")
		self.assertEqual(result["precision"], 4)

	def test_no_change_when_equal(self):
		self.assertEqual(rules.decide_precision(["4"], current=4)["action"], "none")

	def test_floor_of_three(self):
		self.assertEqual(rules.decide_precision(["1"], current=3)["action"], "none")

	def test_ceiling_of_nine(self):
		self.assertEqual(rules.decide_precision(["12"], current=3), {"action": "raise", "from": 3, "to": 9})

	def test_junk_values_ignored(self):
		self.assertEqual(rules.decide_precision([None, "", "abc"], current=3)["action"], "none")


class TestChooseRate(unittest.TestCase):
	def test_prefers_average(self):
		self.assertEqual(rules.choose_rate(36.27, 40.00), (36.27, "AVERAGE_COST"))

	def test_falls_back_to_last(self):
		self.assertEqual(rules.choose_rate(0, 40.00), (40.00, "LAST_COST"))

	def test_sentinel_when_no_cost(self):
		"""Never zero: ERPNext drops the line, and the quantity is lost with it."""
		self.assertEqual(rules.choose_rate(0, 0), (rules.NO_COST_SENTINEL, "sentinel"))

	def test_never_returns_zero(self):
		for average, last in ((0, 0), (None, None), (0, None)):
			self.assertGreater(rules.choose_rate(average, last)[0], 0)


class TestDrift(unittest.TestCase):
	def test_rounding_is_not_drift(self):
		"""Intacct holds 4 decimals, ERPNext stored 3 — 43 false alarms on a clean import."""
		self.assertFalse(rules.is_drift(8016.1265, 8016.126, precision=3))

	def test_real_difference_is_drift(self):
		self.assertTrue(rules.is_drift(8016.0, 8015.0, precision=3))

	def test_tolerance_follows_precision(self):
		self.assertFalse(rules.is_drift(1.00005, 1.0, precision=4))
		self.assertTrue(rules.is_drift(1.5, 1.0, precision=4))


class TestConversions(unittest.TestCase):
	def test_stock_unit_is_always_one(self):
		conversions, missing = rules.build_conversions(
			"Kilograms", ("Drum", 25.0), (None, None), {"Kilograms", "Drum"}
		)
		self.assertEqual(conversions["Kilograms"], 1.0)
		self.assertEqual(conversions["Drum"], 25.0)
		self.assertFalse(missing)

	def test_purchase_unit_cannot_overwrite_stock_unit(self):
		conversions, _ = rules.build_conversions(
			"Kilograms", ("Kilograms", 25.0), (None, None), {"Kilograms"}
		)
		self.assertEqual(conversions["Kilograms"], 1.0)

	def test_unknown_unit_is_reported_not_written(self):
		conversions, missing = rules.build_conversions(
			"Kilograms", ("Drum", 25.0), (None, None), {"Kilograms"}
		)
		self.assertNotIn("Drum", conversions)
		self.assertIn("Drum", missing)

	def test_no_base_unit_yields_no_table(self):
		"""ERPNext requires the stock UOM present with factor 1, or validation fails."""
		conversions, missing = rules.build_conversions(None, ("Drum", 25.0), (None, None), {"Drum"})
		self.assertEqual(conversions, {})


class TestItemType(unittest.TestCase):
	def test_inventory_is_stock(self):
		self.assertTrue(rules.is_stock_item("Inventory"))

	def test_stockable_kit_is_stock(self):
		"""Got this wrong once: the BOM built fine and only manufacturing failed."""
		self.assertTrue(rules.is_stock_item("Stockable Kit"))

	def test_plain_kit_is_not_stock(self):
		self.assertFalse(rules.is_stock_item("Kit"))

	def test_non_inventory_is_not_stock(self):
		self.assertFalse(rules.is_stock_item("Non-Inventory"))

	def test_blank_is_not_stock(self):
		self.assertFalse(rules.is_stock_item(None))


class TestKitBuildOrder(unittest.TestCase):
	def test_child_before_parent(self):
		"""A parent must be built after its sub-assembly, or ERPNext treats it as raw."""
		recipes = {
			"PARENT": [{"item_code": "CHILD"}, {"item_code": "RAW"}],
			"CHILD": [{"item_code": "RAW"}],
		}
		order, circular = rules.kit_build_order({"PARENT", "CHILD"}, recipes)
		self.assertLess(order.index("CHILD"), order.index("PARENT"))
		self.assertFalse(circular)

	def test_three_levels(self):
		recipes = {
			"TOP": [{"item_code": "MID"}],
			"MID": [{"item_code": "BOTTOM"}],
			"BOTTOM": [{"item_code": "RAW"}],
		}
		order, _ = rules.kit_build_order({"TOP", "MID", "BOTTOM"}, recipes)
		self.assertEqual(order, ["BOTTOM", "MID", "TOP"])

	def test_circular_recipe_terminates(self):
		"""Intacct lets a kit contain itself. ERPNext cannot explode it, nor can a factory."""
		recipes = {"A": [{"item_code": "B"}], "B": [{"item_code": "A"}]}
		order, circular = rules.kit_build_order({"A", "B"}, recipes)
		self.assertEqual(order, [])
		self.assertEqual(sorted(circular), ["A", "B"])

	def test_cancel_order_is_the_reverse(self):
		"""Cancellation must be parents first — ERPNext refuses while a parent links."""
		recipes = {"TOP": [{"item_code": "MID"}], "MID": [{"item_code": "RAW"}]}
		order, _ = rules.kit_build_order({"TOP", "MID"}, recipes)
		self.assertEqual(list(reversed(order)), ["TOP", "MID"])


if __name__ == "__main__":
	unittest.main()
