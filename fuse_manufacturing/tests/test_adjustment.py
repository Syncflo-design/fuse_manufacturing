"""Tests for stock adjustments — Material Receipt in, Material Issue out.

Same asymmetry as everywhere else in Intacct: the increase definition values the movement
and the decrease does not. Getting that backwards sends a cost on a leg Intacct will
ignore, and omits it on the one that needs it.
"""

import unittest

from fuse_manufacturing import rules

LINES = [
	{"item_code": "RMNR20", "qty": 30.21, "uom": "Kilograms", "warehouse": "JHB-MIX",
	 "rate": 36.27692, "bin": "BIN0023"},
	{"item_code": "11003190", "qty": 5, "uom": "Kilograms", "warehouse": "JHB-DIS",
	 "rate": 28.22174, "bin": None},
]


class TestIncrease(unittest.TestCase):
	def test_carries_cost(self):
		"""SYS-CC Adjustment Increase has UPDATES_COST=true."""
		legs = rules.adjustment_legs(LINES, increase=True)
		self.assertEqual([leg["cost"] for leg in legs], [36.27692, 28.22174])

	def test_zero_cost_is_refused(self):
		with self.assertRaises(ValueError) as caught:
			rules.adjustment_legs([dict(LINES[0], rate=0)], increase=True)
		self.assertIn("overwrite", str(caught.exception))

	def test_missing_cost_is_refused(self):
		bare = {k: v for k, v in LINES[0].items() if k != "rate"}
		with self.assertRaises(ValueError):
			rules.adjustment_legs([bare], increase=True)


class TestDecrease(unittest.TestCase):
	def test_carries_no_cost(self):
		"""Decrease has UPDATES_COST=false — Intacct removes it at its own valuation."""
		for leg in rules.adjustment_legs(LINES, increase=False):
			self.assertNotIn("cost", leg)

	def test_zero_cost_is_fine_going_out(self):
		"""No cost is sent, so a missing rate cannot do any damage."""
		legs = rules.adjustment_legs([dict(LINES[0], rate=0)], increase=False)
		self.assertEqual(len(legs), 1)


class TestBothDirections(unittest.TestCase):
	def test_quantities_are_positive(self):
		for increase in (True, False):
			for leg in rules.adjustment_legs(LINES, increase=increase):
				self.assertGreater(leg["quantity"], 0)

	def test_negative_quantity_is_refused(self):
		"""A negative on a decrease definition double-negates and adds stock."""
		with self.assertRaises(ValueError):
			rules.adjustment_legs([dict(LINES[0], qty=-5)], increase=False)

	def test_zero_quantity_is_refused(self):
		with self.assertRaises(ValueError):
			rules.adjustment_legs([dict(LINES[0], qty=0)], increase=True)

	def test_missing_unit_is_refused(self):
		bare = {k: v for k, v in LINES[0].items() if k != "uom"}
		with self.assertRaises(ValueError):
			rules.adjustment_legs([bare], increase=True)

	def test_missing_warehouse_is_refused(self):
		with self.assertRaises(ValueError):
			rules.adjustment_legs([dict(LINES[0], warehouse=None)], increase=True)

	def test_empty_adjustment_is_refused(self):
		with self.assertRaises(ValueError):
			rules.adjustment_legs([], increase=True)

	def test_bins_are_carried(self):
		legs = rules.adjustment_legs(LINES, increase=True)
		self.assertEqual([leg["bin"] for leg in legs], ["BIN0023", None])

	def test_round_trip_nets_to_zero(self):
		"""Receipt then its reversal leaves the warehouse where it started."""
		out = rules.adjustment_legs(LINES, increase=True)
		back = rules.adjustment_legs(LINES, increase=False)
		for forward, reverse in zip(out, back, strict=True):
			self.assertEqual(forward["item_id"], reverse["item_id"])
			self.assertEqual(forward["warehouse_id"], reverse["warehouse_id"])
			self.assertAlmostEqual(forward["quantity"] - reverse["quantity"], 0)


class TestAdjustmentDocumentNumbers(unittest.TestCase):
	"""Neither cycle-count definition has a numbering scheme."""

	def test_reversal_number_differs_from_the_original(self):
		self.assertNotEqual(
			rules.document_number_for("Stock Entry", "MAT-STE-2026-00009", "adjustment"),
			rules.document_number_for("Stock Entry", "MAT-STE-2026-00009", "adjustment-reverse"),
		)

	def test_adjustment_number_differs_from_a_manufacture_reversal(self):
		"""Same document, different purposes, must not collide."""
		self.assertNotEqual(
			rules.document_number_for("Stock Entry", "MAT-STE-2026-00009", "adjustment"),
			rules.document_number_for("Stock Entry", "MAT-STE-2026-00009", "manufacture-reverse"),
		)


if __name__ == "__main__":
	unittest.main()
