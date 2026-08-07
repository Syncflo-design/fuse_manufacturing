"""Tests for warehouse transfer legs.

No Frappe, no network. The rules here are the ones Intacct rejects — or worse, accepts
and gets wrong.
"""

import unittest

from fuse_manufacturing import rules


def line(**overrides):
	base = {
		"item_code": "11003190",
		"qty": 10,
		"uom": "Kilograms",
		"from_warehouse": "JHB-DIS",
		"to_warehouse": "CPT-DIS",
	}
	base.update(overrides)
	return base


class TestTransferLegs(unittest.TestCase):
	def test_one_line_becomes_two_legs(self):
		"""A transfer is ONE document with both halves. One side alone is an adjustment."""
		legs = rules.transfer_legs([line()])
		self.assertEqual(len(legs), 2)
		self.assertEqual([leg["in_out"] for leg in legs], ["O", "I"])

	def test_out_leg_is_the_source(self):
		legs = rules.transfer_legs([line()])
		self.assertEqual(legs[0]["warehouse_id"], "JHB-DIS")
		self.assertEqual(legs[1]["warehouse_id"], "CPT-DIS")

	def test_quantities_are_positive_on_both_legs(self):
		"""Direction comes from IN_OUT. Send -10 and Intacct takes it literally."""
		legs = rules.transfer_legs([line(qty=10)])
		self.assertTrue(all(leg["quantity"] > 0 for leg in legs))

	def test_negative_quantity_refused(self):
		with self.assertRaises(ValueError):
			rules.transfer_legs([line(qty=-10)])

	def test_zero_quantity_refused(self):
		with self.assertRaises(ValueError):
			rules.transfer_legs([line(qty=0)])

	def test_same_warehouse_refused(self):
		"""Intacct would accept it and move nothing, which reads as a successful post."""
		with self.assertRaises(ValueError):
			rules.transfer_legs([line(to_warehouse="JHB-DIS")])

	def test_missing_warehouse_refused(self):
		with self.assertRaises(ValueError):
			rules.transfer_legs([line(from_warehouse=None)])

	def test_missing_unit_refused(self):
		"""A blank unit fails at Intacct with BL03000018 — catch it here instead."""
		with self.assertRaises(ValueError):
			rules.transfer_legs([line(uom=None)])

	def test_several_lines_keep_their_pairs(self):
		legs = rules.transfer_legs([line(), line(item_code="11003215", qty=5)])
		self.assertEqual(len(legs), 4)
		self.assertEqual(legs[2]["item_id"], "11003215")
		self.assertEqual(legs[2]["quantity"], 5)
		self.assertEqual(legs[3]["in_out"], "I")


if __name__ == "__main__":
	unittest.main()
