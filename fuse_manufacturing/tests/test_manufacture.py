"""Tests for the manufacturing legs and produced cost.

No Frappe, no network. The produced cost is the number Intacct accepts and books, so it
gets the most attention here.
"""

import unittest

from fuse_manufacturing import rules


def consumed(**overrides):
	base = {"item_code": "RMNR20", "qty": 2, "uom": "Kilograms", "warehouse": "JHB-MIX", "rate": 36.0}
	base.update(overrides)
	return base


class TestProducedUnitCost(unittest.TestCase):
	def test_derived_from_what_was_consumed(self):
		"""10 kg at R36 plus 5 kg at R20 = R460, over 5 units = R92 each."""
		lines = [consumed(qty=10, rate=36.0), consumed(item_code="RMN550", qty=5, rate=20.0)]
		self.assertAlmostEqual(rules.produced_unit_cost(lines, 5), 92.0)

	def test_single_component(self):
		self.assertAlmostEqual(rules.produced_unit_cost([consumed(qty=4, rate=25.0)], 2), 50.0)

	def test_zero_produced_refused(self):
		"""Would be a division by zero, and a run that made nothing is not a run."""
		with self.assertRaises(ValueError):
			rules.produced_unit_cost([consumed()], 0)

	def test_negative_produced_refused(self):
		with self.assertRaises(ValueError):
			rules.produced_unit_cost([consumed()], -5)

	def test_zero_cost_components_give_zero_cost(self):
		self.assertEqual(rules.produced_unit_cost([consumed(rate=0)], 1), 0.0)


class TestManufactureLegs(unittest.TestCase):
	def legs(self, **overrides):
		kwargs = {
			"consumed": [consumed(qty=10, rate=36.0)],
			"produced_item": "MTUFF",
			"produced_qty": 5,
			"produced_uom": "Kilograms",
			"warehouse": "JHB-MIX",
		}
		kwargs.update(overrides)
		return rules.manufacture_legs(**kwargs)

	def test_two_separate_legs(self):
		legs = self.legs()
		self.assertEqual(len(legs["consume"]), 1)
		self.assertEqual(len(legs["produce"]), 1)

	def test_consume_leg_carries_no_cost(self):
		"""UPDATES_COST=false — sending a cost would override Intacct's own valuation."""
		self.assertIsNone(self.legs()["consume"][0].get("cost"))

	def test_produce_leg_carries_cost(self):
		"""UPDATES_COST=true — 10 kg at R36 over 5 units = R72 each."""
		self.assertAlmostEqual(self.legs()["produce"][0]["cost"], 72.0)

	def test_all_quantities_positive(self):
		"""Each definition applies its own sign. A negative double-negates a decrease."""
		legs = self.legs()
		self.assertTrue(all(line["quantity"] > 0 for line in legs["consume"] + legs["produce"]))

	def test_nothing_consumed_refused(self):
		with self.assertRaises(ValueError):
			self.legs(consumed=[])

	def test_zero_produced_refused(self):
		with self.assertRaises(ValueError):
			self.legs(produced_qty=0)

	def test_missing_produced_unit_refused(self):
		with self.assertRaises(ValueError):
			self.legs(produced_uom=None)

	def test_negative_consumed_qty_refused(self):
		with self.assertRaises(ValueError):
			self.legs(consumed=[consumed(qty=-1)])

	def test_missing_consumed_unit_refused(self):
		with self.assertRaises(ValueError):
			self.legs(consumed=[consumed(uom=None)])

	def test_bin_carried_through_when_present(self):
		legs = self.legs(consumed=[consumed(bin="B001")])
		self.assertEqual(legs["consume"][0]["bin"], "B001")


if __name__ == "__main__":
	unittest.main()
