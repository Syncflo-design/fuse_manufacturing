"""Tests for mirroring open Intacct purchase orders as stock on order.

Two things carry real risk here. Intacct returns dates in US order whatever the company's
locale, so a South African reading of 08/07/2026 is a month out and nothing fails. And an
order that has not changed must be left alone, or every sync cancels and rebuilds it and
the stock-on-order figure flickers daily.
"""

import unittest

from fuse_manufacturing import rules


class TestIntacctDate(unittest.TestCase):
	def test_us_order_not_local_order(self):
		"""08/07/2026 is 8 July to Intacct, 7 August to a South African. Intacct wins."""
		self.assertEqual(rules.intacct_date("08/07/2026"), "2026-08-07")

	def test_the_due_date_we_actually_read_live(self):
		"""IPO00000007, the one open order — Date due 2026-07-28 on the Intacct screen."""
		self.assertEqual(rules.intacct_date("07/28/2026"), "2026-07-28")

	def test_day_that_cannot_be_a_month(self):
		self.assertEqual(rules.intacct_date("12/25/2026"), "2026-12-25")

	def test_empty_is_none_not_today(self):
		"""A missing due date must not become a date — the order gets reported instead."""
		for empty in ("", "   ", None):
			self.assertIsNone(rules.intacct_date(empty))

	def test_unparseable_is_none(self):
		for bad in ("2026-07-28", "28/07/2026", "not a date", "13/45/2026"):
			self.assertIsNone(rules.intacct_date(bad))

	def test_whitespace_is_tolerated(self):
		self.assertEqual(rules.intacct_date("  07/28/2026  "), "2026-07-28")


LINE = {"item_code": "10115386", "qty": 150.0, "warehouse": "CPT-CON - LRC", "schedule_date": "2026-07-28"}


class TestPurchaseOrderSignature(unittest.TestCase):
	def test_identical_orders_match(self):
		self.assertEqual(
			rules.purchase_order_signature([LINE]),
			rules.purchase_order_signature([dict(LINE)]),
		)

	def test_line_order_is_not_a_change(self):
		"""Intacct may return the same lines in a different sequence."""
		other = dict(LINE, item_code="RMNR20")
		self.assertEqual(
			rules.purchase_order_signature([LINE, other]),
			rules.purchase_order_signature([other, LINE]),
		)

	def test_quantity_change_is_detected(self):
		"""The whole point: Intacct received some, so less is still on order."""
		self.assertNotEqual(
			rules.purchase_order_signature([LINE]),
			rules.purchase_order_signature([dict(LINE, qty=100.0)]),
		)

	def test_due_date_change_is_detected(self):
		self.assertNotEqual(
			rules.purchase_order_signature([LINE]),
			rules.purchase_order_signature([dict(LINE, schedule_date="2026-08-15")]),
		)

	def test_warehouse_change_is_detected(self):
		self.assertNotEqual(
			rules.purchase_order_signature([LINE]),
			rules.purchase_order_signature([dict(LINE, warehouse="JHB-DIS - LRC")]),
		)

	def test_dropped_line_is_detected(self):
		other = dict(LINE, item_code="RMNR20")
		self.assertNotEqual(
			rules.purchase_order_signature([LINE, other]),
			rules.purchase_order_signature([LINE]),
		)

	def test_date_object_and_string_compare_equal(self):
		"""ERPNext hands back a date, Intacct a string — that is not a change."""
		import datetime

		self.assertEqual(
			rules.purchase_order_signature([LINE]),
			rules.purchase_order_signature([dict(LINE, schedule_date=datetime.date(2026, 7, 28))]),
		)

	def test_float_noise_is_not_a_change(self):
		"""150 and 150.0000000001 are the same order, not a reason to rebuild it."""
		self.assertEqual(
			rules.purchase_order_signature([LINE]),
			rules.purchase_order_signature([dict(LINE, qty=150.0000000001)]),
		)


if __name__ == "__main__":
	unittest.main()
