"""Tests for demand netting and BOM explosion.

No Frappe, no site. The cases are the ones that give a wrong reorder figure quietly: a
level netted on gross instead of net, an item appearing at two depths, a compound that
is both sold and consumed.
"""

import unittest

from fuse_manufacturing import planning

# Tread -> compound -> rubber, the Leader Rubber shape. 1 kg of tread takes 1 kg of
# compound; 1 kg of compound takes 0.25 kg of natural rubber and 0.3 kg of carbon black.
BOMS = {
	"TREAD": [("COMPOUND", 1.0)],
	"COMPOUND": [("RUBBER", 0.25), ("BLACK", 0.3)],
}


def by_item(rows):
	return {row["item_code"]: row for row in rows}


class TestLowLevelCodes(unittest.TestCase):
	def test_levels_follow_the_recipe(self):
		levels = planning.low_level_codes(["TREAD"], BOMS)
		self.assertEqual(levels, {"TREAD": 0, "COMPOUND": 1, "RUBBER": 2, "BLACK": 2})

	def test_deepest_level_wins(self):
		"""Rubber used directly in the tread AND in its compound sits at the compound's depth.

		Otherwise rubber would be netted before the compound had asked for any.
		"""
		boms = {"TREAD": [("COMPOUND", 1.0), ("RUBBER", 0.1)], "COMPOUND": [("RUBBER", 0.25)]}
		levels = planning.low_level_codes(["TREAD"], boms)
		self.assertEqual(levels["RUBBER"], 2)

	def test_recipe_loop_does_not_hang(self):
		boms = {"A": [("B", 1.0)], "B": [("A", 1.0)]}
		levels = planning.low_level_codes(["A"], boms)
		self.assertLessEqual(max(levels.values()), planning.MAX_DEPTH)


class TestExplode(unittest.TestCase):
	def test_shortage_flows_down_the_levels(self):
		rows = by_item(planning.explode({"TREAD": 100.0}, BOMS))
		self.assertEqual(rows["TREAD"]["net"], 100.0)
		self.assertEqual(rows["COMPOUND"]["required"], 100.0)
		self.assertEqual(rows["COMPOUND"]["net"], 100.0)
		self.assertAlmostEqual(rows["RUBBER"]["net"], 25.0)
		self.assertAlmostEqual(rows["BLACK"]["net"], 30.0)

	def test_stock_at_a_level_stops_the_demand_there(self):
		"""Compound on the shelf does not create demand for the rubber already in it."""
		rows = by_item(planning.explode({"TREAD": 100.0}, BOMS, on_hand={"COMPOUND": 100.0}))
		self.assertEqual(rows["COMPOUND"]["net"], 0.0)
		self.assertEqual(rows["RUBBER"]["net"], 0.0)
		# Still listed, so the planner can see it was covered rather than forgotten.
		self.assertIn("RUBBER", rows)

	def test_target_stock_is_demand(self):
		"""The spreadsheet's Max: keep 30 on the shelf on top of what is ordered."""
		rows = by_item(planning.explode({"TREAD": 40.0}, BOMS, on_hand={"TREAD": 50.0}, target={"TREAD": 30.0}))
		self.assertEqual(rows["TREAD"]["net"], 20.0)

	def test_never_negative(self):
		rows = by_item(planning.explode({"TREAD": 10.0}, BOMS, on_hand={"TREAD": 500.0}))
		self.assertEqual(rows["TREAD"]["net"], 0.0)

	def test_works_orders_cover_made_items_and_purchase_orders_cover_bought(self):
		rows = by_item(
			planning.explode(
				{"TREAD": 100.0},
				BOMS,
				in_progress={"COMPOUND": 60.0, "RUBBER": 999.0},
				on_order={"RUBBER": 5.0, "COMPOUND": 999.0},
			)
		)
		self.assertEqual(rows["COMPOUND"]["net"], 40.0)
		self.assertEqual(rows["COMPOUND"]["in_progress"], 60.0)
		self.assertEqual(rows["COMPOUND"]["on_order"], 0.0)
		self.assertAlmostEqual(rows["RUBBER"]["net"], 5.0)
		self.assertEqual(rows["RUBBER"]["on_order"], 5.0)
		self.assertEqual(rows["RUBBER"]["in_progress"], 0.0)

	def test_sold_compound_keeps_its_own_orders(self):
		"""A compound sold by the kilo AND used in a tread is netted once, with both demands."""
		rows = by_item(planning.explode({"TREAD": 100.0, "COMPOUND": 50.0}, BOMS))
		self.assertEqual(rows["COMPOUND"]["demand"], 50.0)
		self.assertEqual(rows["COMPOUND"]["required"], 100.0)
		self.assertEqual(rows["COMPOUND"]["net"], 150.0)
		self.assertEqual(rows["COMPOUND"]["stage"], planning.FINISHED)
		self.assertAlmostEqual(rows["RUBBER"]["net"], 37.5)

	def test_stages(self):
		rows = by_item(planning.explode({"TREAD": 1.0, "COUPLER": 2.0}, BOMS))
		self.assertEqual(rows["TREAD"]["stage"], planning.FINISHED)
		self.assertEqual(rows["COUPLER"]["stage"], planning.FINISHED)
		self.assertEqual(rows["COUPLER"]["kind"], planning.BUY)
		self.assertEqual(rows["COMPOUND"]["stage"], planning.SUB_ASSEMBLY)
		self.assertEqual(rows["RUBBER"]["stage"], planning.RAW_MATERIAL)

	def test_rows_come_out_in_level_order(self):
		rows = planning.explode({"TREAD": 1.0}, BOMS)
		self.assertEqual([row["level"] for row in rows], sorted(row["level"] for row in rows))


if __name__ == "__main__":
	unittest.main()
