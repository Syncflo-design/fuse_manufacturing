"""Tests for undoing a production run.

The trap this guards is that a reversal is NOT the forward pair negated. Intacct's
definitions are asymmetric: the cost always rides the increase leg, so flipping the
direction moves the cost from the finished goods to the components. Building the reversal
by mirroring the forward legs would return the quantities and lose the money.
"""

import unittest

from fuse_manufacturing import rules

CONSUMED = [
	{"item_code": "RMNR20", "qty": 30.21, "uom": "Kilograms", "warehouse": "JHB-MIX", "rate": 36.27692, "bin": "BIN0023"},
	{"item_code": "RMSKIM", "qty": 24.17, "uom": "Kilograms", "warehouse": "JHB-MIX", "rate": 31.35086, "bin": "BIN0023"},
]


def reverse(**overrides):
	kwargs = {
		"consumed": CONSUMED,
		"produced_item": "MTUFF",
		"produced_qty": 100,
		"produced_uom": "Kilograms",
		"warehouse": "JHB-MIX",
	}
	kwargs.update(overrides)
	return rules.manufacture_reversal_legs(**kwargs)


class TestManufactureReversal(unittest.TestCase):
	def test_components_carry_the_cost_they_left_at(self):
		"""The whole point: Backflush Incr has UPDATES_COST=true."""
		legs = reverse()
		self.assertEqual([line["cost"] for line in legs["unconsume"]], [36.27692, 31.35086])

	def test_finished_goods_leg_carries_no_cost(self):
		"""Run Decrease has UPDATES_COST=false — Intacct values it itself."""
		self.assertNotIn("cost", reverse()["unproduce"][0])

	def test_cost_is_not_the_forward_unit_cost(self):
		"""Guards against 'reverse = forward negated', which would send 33.86 per component."""
		forward = rules.manufacture_legs(
			consumed=CONSUMED, produced_item="MTUFF", produced_qty=100,
			produced_uom="Kilograms", warehouse="JHB-MIX",
		)
		unit_cost = forward["produce"][0]["cost"]
		for line in reverse()["unconsume"]:
			self.assertNotAlmostEqual(line["cost"], unit_cost)

	def test_quantities_are_positive_on_both_legs(self):
		"""Each definition applies its own sign; a negative double-negates."""
		legs = reverse()
		for line in legs["unproduce"] + legs["unconsume"]:
			self.assertGreater(line["quantity"], 0)

	def test_quantities_match_the_forward_run_exactly(self):
		legs = reverse()
		self.assertEqual(legs["unproduce"][0]["quantity"], 100)
		self.assertEqual([line["quantity"] for line in legs["unconsume"]], [30.21, 24.17])

	def test_bins_are_carried_back(self):
		self.assertEqual([line["bin"] for line in reverse()["unconsume"]], ["BIN0023", "BIN0023"])

	def test_zero_cost_component_is_refused(self):
		"""Sending zero on a cost-updating definition overwrites Intacct's valuation."""
		zero = [dict(CONSUMED[0], rate=0)]
		with self.assertRaises(ValueError) as caught:
			reverse(consumed=zero)
		self.assertIn("overwrite", str(caught.exception))

	def test_missing_cost_is_refused(self):
		no_rate = [{k: v for k, v in CONSUMED[0].items() if k != "rate"}]
		with self.assertRaises(ValueError):
			reverse(consumed=no_rate)

	def test_nothing_consumed_is_refused(self):
		with self.assertRaises(ValueError):
			reverse(consumed=[])

	def test_non_positive_produced_qty_is_refused(self):
		for bad in (0, -100):
			with self.assertRaises(ValueError):
				reverse(produced_qty=bad)

	def test_missing_unit_is_refused(self):
		with self.assertRaises(ValueError):
			reverse(produced_uom="")
		with self.assertRaises(ValueError):
			reverse(consumed=[{k: v for k, v in CONSUMED[0].items() if k != "uom"}])

	def test_round_trip_nets_to_zero_on_quantity(self):
		"""Forward then reverse leaves the warehouse where it started."""
		forward = rules.manufacture_legs(
			consumed=CONSUMED, produced_item="MTUFF", produced_qty=100,
			produced_uom="Kilograms", warehouse="JHB-MIX",
		)
		back = reverse()

		net = {}
		for line in forward["produce"] + back["unconsume"]:
			net[line["item_id"]] = net.get(line["item_id"], 0) + line["quantity"]
		for line in forward["consume"] + back["unproduce"]:
			net[line["item_id"]] = net.get(line["item_id"], 0) - line["quantity"]

		for item, movement in net.items():
			self.assertAlmostEqual(movement, 0, msg=f"{item} did not net to zero")


class TestReversalControlIds(unittest.TestCase):
	def test_reversal_id_differs_from_the_forward_post(self):
		"""Same ID would make Intacct reject the reversal as a duplicate of the original."""
		self.assertNotEqual(
			rules.control_id_for("Stock Entry", "MAT-STE-2026-00002", "manufacture"),
			rules.control_id_for("Stock Entry", "MAT-STE-2026-00002", "manufacture-reverse"),
		)

	def test_reversal_id_is_stable(self):
		"""A retried reversal must not post a second time."""
		self.assertEqual(
			rules.control_id_for("Stock Entry", "MAT-STE-2026-00002", "manufacture-reverse"),
			rules.control_id_for("Stock Entry", "MAT-STE-2026-00002", "manufacture-reverse"),
		)


if __name__ == "__main__":
	unittest.main()
