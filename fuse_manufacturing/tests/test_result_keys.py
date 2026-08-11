"""Tests for reading the record key out of an Intacct response.

Intacct returns it in two different shapes. Handling only one loses the key silently —
the posting succeeds and the traceability does not, which is exactly what happened on the
first live warehouse transfer.
"""

import unittest

from fuse_manufacturing import rules

# The real response from the first successful transfer, RECORDNO 23.
GENERIC_CREATE = """<response><operation><result>
  <status>success</status><function>create</function>
  <data listtype="objects" count="1"><ictransfer><RECORDNO>23</RECORDNO></ictransfer></data>
</result></operation></response>"""

KEY_FORM = """<response><operation><result>
  <status>success</status><function>create_ictransaction</function><key>4711</key>
</result></operation></response>"""

TWO_RESULTS = """<response><operation>
  <result><function>create_ictransaction</function><key>100</key></result>
  <result><function>create_ictransaction</function><key>101</key></result>
</operation></response>"""


class TestResultKeys(unittest.TestCase):
	def test_generic_create_returns_recordno(self):
		"""The shape that silently returned nothing on the first live post."""
		self.assertEqual(rules.result_keys(GENERIC_CREATE), ["23"])

	def test_key_element_form(self):
		self.assertEqual(rules.result_keys(KEY_FORM), ["4711"])

	def test_one_entry_per_result_in_order(self):
		"""Callers line these up against the functions they sent."""
		self.assertEqual(rules.result_keys(TWO_RESULTS), ["100", "101"])

	def test_result_with_no_key_is_none_not_dropped(self):
		"""Dropping it would shift every later key onto the wrong function."""
		xml = """<response><operation>
		  <result><function>a</function></result>
		  <result><function>b</function><key>7</key></result>
		</operation></response>"""
		self.assertEqual(rules.result_keys(xml), [None, "7"])

	def test_no_results_gives_empty(self):
		self.assertEqual(rules.result_keys("<response><operation/></response>"), [])


if __name__ == "__main__":
	unittest.main()
