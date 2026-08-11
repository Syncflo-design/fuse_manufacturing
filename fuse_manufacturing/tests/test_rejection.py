"""Tests for spotting a rejection Intacct reports with HTTP 200.

This is the last thing standing between a rejected posting and an ERPNext document that
claims it succeeded. The first version tested for the word "failure" and let `aborted`
through — a real reversal was rolled back by Intacct, recorded as a success, and the
ERPNext cancel went ahead on the strength of it. The two systems then disagreed about
stock that had physically moved.

So the rule is a whitelist: anything that is not "success" is a rejection.
"""

import unittest

from fuse_manufacturing import rules

# The exact response that got through, on MAT-STE-2026-00002's reversal, 2026-08-11.
ABORTED = """<response>
  <control><status>success</status><controlid>fuse-3a7dc437b514ff41</controlid></control>
  <operation>
    <authentication><status>success</status></authentication>
    <result>
      <status>aborted</status>
      <function>create_ictransaction</function>
      <errormessage>
        <error><errorno>PL01000127</errorno><description/>
          <description2>Document Number is missing</description2>
          <correction>Make desired changes and press Save to continue.</correction></error>
        <error><errorno>XL03000009</errorno><description/>
          <description2>The entire transaction in this operation has been rolled back due to an error.</description2>
          <correction/></error>
      </errormessage>
    </result>
  </operation>
</response>"""

SUCCESS = """<response>
  <control><status>success</status></control>
  <operation>
    <authentication><status>success</status></authentication>
    <result><status>success</status><function>create_ictransaction</function>
      <key>Manufacturing Run Increase-MR00000091</key></result>
  </operation>
</response>"""


class TestRejectionErrors(unittest.TestCase):
	def test_aborted_is_a_rejection(self):
		"""The one that got through and let ERPNext and Intacct diverge."""
		self.assertTrue(rules.rejection_errors(ABORTED))

	def test_aborted_reports_intacct_own_error_text(self):
		errors = rules.rejection_errors(ABORTED)
		self.assertIn("PL01000127", errors[0])
		self.assertIn("Document Number is missing", errors[0])

	def test_rolled_back_notice_is_kept(self):
		"""Operators need to know nothing was committed, not just that something failed."""
		self.assertIn("rolled back", " ".join(rules.rejection_errors(ABORTED)))

	def test_success_is_not_a_rejection(self):
		self.assertEqual(rules.rejection_errors(SUCCESS), [])

	def test_failure_is_still_caught(self):
		"""The case the original version did handle — must not regress."""
		xml = "<response><operation><result><status>failure</status>" \
		      "<errormessage><error><errorno>BL03000018</errorno>" \
		      "<description2>Missing unit</description2></error></errormessage>" \
		      "</result></operation></response>"
		self.assertIn("BL03000018", rules.rejection_errors(xml)[0])

	def test_unknown_status_word_is_a_rejection(self):
		"""A whitelist, so a word Intacct has not used before still stops the post."""
		xml = "<response><operation><result><status>partially_applied</status>" \
		      "</result></operation></response>"
		self.assertTrue(rules.rejection_errors(xml))

	def test_rejection_without_error_detail_still_raises(self):
		"""Returning [] here would read as acceptance."""
		xml = "<response><operation><result><status>aborted</status></result></operation></response>"
		errors = rules.rejection_errors(xml)
		self.assertTrue(errors)
		self.assertIn("no error detail", errors[0])

	def test_failure_in_control_block_is_caught(self):
		"""A bad sender password fails before any result exists."""
		xml = "<response><control><status>failure</status></control>" \
		      "<errormessage><error><errorno>XL03000006</errorno>" \
		      "<description2>Login information is incorrect</description2>" \
		      "</error></errormessage></response>"
		self.assertIn("XL03000006", rules.rejection_errors(xml)[0])

	def test_one_aborted_result_among_successes_is_a_rejection(self):
		"""Atomic operations roll back together; a single abort damns the batch."""
		xml = "<response><operation>" \
		      "<result><status>success</status><key>1</key></result>" \
		      "<result><status>aborted</status></result>" \
		      "</operation></response>"
		self.assertTrue(rules.rejection_errors(xml))

	def test_empty_status_text_is_ignored(self):
		"""Absence of a status is not a claim of failure."""
		xml = "<response><operation><result><status></status>" \
		      "<key>7</key></result></operation></response>"
		self.assertEqual(rules.rejection_errors(xml), [])


if __name__ == "__main__":
	unittest.main()
