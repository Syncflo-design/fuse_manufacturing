"""Tests for splitting a Manufacture entry into consumed and produced rows.

The first version classified by elimination and dropped rows in silence: a second finished
item overwrote the first, and any row with a destination but no source vanished. Nothing
failed, nothing was logged — Intacct simply received less than happened.

So these tests are mostly about what must be REFUSED.
"""

import unittest

from fuse_manufacturing import rules

COMPONENT = {"item_code": "RMNR20", "qty": 30.21, "is_finished_item": 0,
             "s_warehouse": "JHB-MIX", "t_warehouse": None, "rate": 36.27692}
FINISHED = {"item_code": "MTUFF", "qty": 100, "is_finished_item": 1,
            "s_warehouse": None, "t_warehouse": "JHB-MIX", "rate": 33.8585}


class TestNormalRun(unittest.TestCase):
	def test_splits_components_from_the_finished_item(self):
		split = rules.classify_manufacture_rows([COMPONENT, FINISHED])
		self.assertEqual(split["problems"], [])
		self.assertEqual(split["produced"]["item_code"], "MTUFF")
		self.assertEqual([row["item_code"] for row in split["consumed"]], ["RMNR20"])

	def test_the_finished_item_is_never_also_consumed(self):
		split = rules.classify_manufacture_rows([COMPONENT, FINISHED])
		self.assertNotIn("MTUFF", [row["item_code"] for row in split["consumed"]])

	def test_rates_survive_the_split(self):
		"""The reversal returns components at these rates, so losing them is expensive."""
		split = rules.classify_manufacture_rows([COMPONENT, FINISHED])
		self.assertEqual(split["consumed"][0]["rate"], 36.27692)


class TestRefusals(unittest.TestCase):
	def test_two_finished_items_are_refused(self):
		"""Used to post as if only the last one had been made."""
		second = dict(FINISHED, item_code="MTUFF-B")
		split = rules.classify_manufacture_rows([COMPONENT, FINISHED, second])
		self.assertTrue(split["problems"])
		self.assertIn("more than one finished item", split["problems"][0])

	def test_two_finished_items_names_both(self):
		second = dict(FINISHED, item_code="MTUFF-B")
		problem = rules.classify_manufacture_rows([COMPONENT, FINISHED, second])["problems"][0]
		self.assertIn("MTUFF", problem)
		self.assertIn("MTUFF-B", problem)

	def test_scrap_output_is_refused_not_skipped(self):
		"""Destination but no source: used to fall through the loop and reach Intacct as nothing."""
		scrap = {"item_code": "SCRAP-RUBBER", "qty": 4, "is_finished_item": 0,
		         "s_warehouse": None, "t_warehouse": "JHB-MIX", "rate": 0}
		split = rules.classify_manufacture_rows([COMPONENT, FINISHED, scrap])
		self.assertTrue(split["problems"])
		self.assertIn("SCRAP-RUBBER", split["problems"][0])

	def test_scrap_is_not_counted_as_consumed(self):
		scrap = {"item_code": "SCRAP-RUBBER", "qty": 4, "is_finished_item": 0,
		         "s_warehouse": None, "t_warehouse": "JHB-MIX", "rate": 0}
		split = rules.classify_manufacture_rows([COMPONENT, FINISHED, scrap])
		self.assertNotIn("SCRAP-RUBBER", [row["item_code"] for row in split["consumed"]])

	def test_row_with_no_warehouse_at_all_is_refused(self):
		orphan = {"item_code": "MYSTERY", "qty": 1, "is_finished_item": 0,
		          "s_warehouse": None, "t_warehouse": None, "rate": 0}
		split = rules.classify_manufacture_rows([COMPONENT, FINISHED, orphan])
		self.assertIn("MYSTERY", " ".join(split["problems"]))

	def test_no_finished_item_is_refused(self):
		split = rules.classify_manufacture_rows([COMPONENT])
		self.assertIn("no finished item", split["problems"][0])

	def test_empty_entry_is_refused(self):
		self.assertTrue(rules.classify_manufacture_rows([])["problems"])

	def test_every_bad_row_is_reported_not_just_the_first(self):
		"""Fixing them one rejection at a time is a bad afternoon."""
		scrap = {"item_code": "SCRAP-RUBBER", "qty": 4, "is_finished_item": 0,
		         "s_warehouse": None, "t_warehouse": "JHB-MIX", "rate": 0}
		orphan = {"item_code": "MYSTERY", "qty": 1, "is_finished_item": 0,
		          "s_warehouse": None, "t_warehouse": None, "rate": 0}
		problems = rules.classify_manufacture_rows([COMPONENT, FINISHED, scrap, orphan])["problems"]
		self.assertEqual(len(problems), 2)

	def test_a_refused_entry_still_reports_what_it_could_read(self):
		"""The message is more use next to the rows it did understand."""
		scrap = {"item_code": "SCRAP-RUBBER", "qty": 4, "is_finished_item": 0,
		         "s_warehouse": None, "t_warehouse": "JHB-MIX", "rate": 0}
		split = rules.classify_manufacture_rows([COMPONENT, FINISHED, scrap])
		self.assertEqual([row["item_code"] for row in split["consumed"]], ["RMNR20"])


class TestSubstitution(unittest.TestCase):
	"""A swapped raw material is just a different consumed row — nothing special."""

	def test_a_substituted_component_is_consumed_normally(self):
		substitute = dict(COMPONENT, item_code="RMNR10", rate=41.5)
		split = rules.classify_manufacture_rows([substitute, FINISHED])
		self.assertEqual(split["problems"], [])
		self.assertEqual(split["consumed"][0]["item_code"], "RMNR10")
		self.assertEqual(split["consumed"][0]["rate"], 41.5)

	def test_an_extra_component_not_on_the_bom_is_consumed_normally(self):
		extra = dict(COMPONENT, item_code="RMSKIM", qty=5)
		split = rules.classify_manufacture_rows([COMPONENT, extra, FINISHED])
		self.assertEqual(split["problems"], [])
		self.assertEqual(len(split["consumed"]), 2)


if __name__ == "__main__":
	unittest.main()
