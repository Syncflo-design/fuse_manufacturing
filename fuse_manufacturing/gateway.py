"""Sage Intacct XML gateway.

Everything that talks to Intacct goes through here. One module, no class hierarchy:
a session, a query, a post.

Why XML and not REST: REST forces every customer through app registration in the Sage
developer portal. The gateway needs only a sender ID plus company credentials.

The constraints encoded below were learned the hard way on the donor app. See
docs/02-intacct-integration.md before changing any of them.
"""

import re
import time
import uuid
import xml.etree.ElementTree as ET

import frappe
import requests

from fuse_manufacturing import rules

# Intacct sessions idle out at around an hour. Twenty minutes is comfortably inside
# that, and a stale one simply forces a fresh login. Re-logging in per call turned one
# kit import into 16 logins on the donor.
SESSION_LIFE_SECONDS = 20 * 60

# Cached per worker process: (session_id, obtained_at_epoch).
_session_cache = {}


def settings():
	return frappe.get_cached_doc("Intacct Settings")


def _require_enabled(cfg):
	if not cfg.enabled:
		frappe.throw("Intacct Settings is not enabled — refusing to contact the gateway.")


# ──────────────────────────────────────────────────────────────────────────────
# Transport
# ──────────────────────────────────────────────────────────────────────────────


# A control ID that is the SAME every time for the same piece of work — what makes a
# retry safe. Lives in rules.py so it is covered by tests that need no site.
control_id_for = rules.control_id_for


def _control(cfg, control_id=None, unique=False):
	"""The <control> block every request carries.

	`unique=True` tells Intacct to enforce control-ID uniqueness — pair it with a
	deterministic control_id on every write.
	"""
	control = ET.Element("control")
	ET.SubElement(control, "senderid").text = cfg.sender_id
	ET.SubElement(control, "password").text = cfg.get_password("sender_password")
	ET.SubElement(control, "controlid").text = control_id or str(uuid.uuid4())
	ET.SubElement(control, "uniqueid").text = "true" if unique else "false"
	ET.SubElement(control, "dtdversion").text = "3.0"
	return control


# Elements whose text is a credential. Redacted before anything is written to the log —
# the request XML carries both the sender password and the user password in clear.
_SECRET_TAGS = ("password", "senderpassword", "userpassword", "sessionid")


def _redact(xml_text):
	"""Strip credentials out of XML before it is stored or shown."""
	for tag in _SECRET_TAGS:
		xml_text = re.sub(
			rf"<{tag}>.*?</{tag}>", f"<{tag}>***</{tag}>", xml_text, flags=re.IGNORECASE | re.DOTALL
		)
	return xml_text


def _log_request(*, function_name, control_id, request_xml, response_xml, status, http_status=None,
                 duration_ms=None, attempt=1, error=None, reference=None, entity_id=None,
                 intacct_key=None):
	"""Record one request. Never raises — a logging failure must not fail the post."""
	try:
		doc = frappe.new_doc("Intacct Request Log")
		doc.function_name = (function_name or "")[:140]
		doc.control_id = (control_id or "")[:140]
		doc.status = status
		doc.http_status = http_status
		doc.duration_ms = duration_ms
		doc.attempt = attempt
		doc.entity_id = entity_id
		doc.intacct_key = intacct_key
		doc.error = (error or "")[:2000] or None
		if reference:
			doc.reference_doctype, doc.reference_name = reference
		doc.request_xml = _redact(request_xml or "")[:100000]
		doc.response_xml = (response_xml or "")[:100000]
		doc.insert(ignore_permissions=True)
		# Commit the log entry on its own.
		#
		# Without this the log is worthless exactly when it matters: a failed post raises,
		# Frappe rolls the transaction back, and the log row rolls back with it. The one
		# record you need to explain what happened disappears because what happened was a
		# failure. Committing here keeps the audit trail independent of the outcome it
		# describes.
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="Intacct request log write failed", message=frappe.get_traceback())


def _retry_after_seconds(response):
	"""Seconds to wait from a Retry-After header, if the server sent a usable one."""
	value = (response.headers.get("Retry-After") or "").strip()
	if not value.isdigit():
		return None
	# Cap it: a pathological header should not park a background job for an hour.
	return min(int(value), 120)


def _is_transient(exc):
	"""Retry a dropped connection; never retry a genuine rejection.

	A 4xx other than 429 will fail identically every time, so retrying it only delays
	the error the caller needs to see.
	"""
	if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
		return True
	message = str(exc).lower()
	return any(
		token in message
		for token in ("timed out", "empty response", "returned 5", "returned 429")
	)


def _post(cfg, request_element, retry=True):
	"""POST one <request> and return the parsed response root.

	`retry=True` for READS: a dropped connection in a several-hundred-page import must
	not fail the whole run, and re-reading is free.

	`retry=False` for WRITES. A write that times out is AMBIGUOUS — Intacct may have
	committed it. Retrying is not safe in the way it looks:
	  - if Intacct did not commit, the retry works;
	  - if Intacct DID commit, the deterministic control ID means the replay is rejected,
	    and that rejection surfaces as a failure. The operator is then told the posting
	    failed when the stock actually moved, and re-does it by hand.
	The honest behaviour is to surface the timeout, record the request in the log, and
	let a human check Intacct. The control ID still protects against a double-post if
	they resubmit.
	"""
	body = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(request_element, encoding="utf-8")
	attempts = (cfg.max_attempts or 3) if retry else 1
	last = None

	for attempt in range(1, attempts + 1):
		try:
			response = requests.post(
				cfg.gateway_url,
				data=body,
				headers={"Content-Type": "application/xml"},
				timeout=cfg.timeout or 300,
			)
			if response.status_code == 429:
				# Rate limited. Honour Retry-After when Intacct sends one rather than
				# guessing — backing off too little on a rate limit is how you turn a
				# pause into a block.
				wait = _retry_after_seconds(response) or (10 * attempt)
				if attempt < attempts:
					time.sleep(wait)
					continue
				raise RuntimeError(f"Intacct gateway returned 429 after {attempts} attempts")
			if response.status_code >= 500:
				raise RuntimeError(f"Intacct gateway returned {response.status_code}")
			if response.status_code >= 400:
				# Genuine rejection — surface it, do not retry.
				raise RuntimeError(
					f"Intacct gateway returned {response.status_code}: {response.text[:500]}"
				)
			if not (response.text or "").strip():
				raise RuntimeError("Intacct gateway returned an empty response (connection dropped or timed out).")
			return ET.fromstring(response.content)
		except Exception as exc:  # noqa: BLE001 - retry decision is made by _is_transient
			last = exc
			if attempt >= attempts or not _is_transient(exc):
				raise
			time.sleep(2 * attempt)  # 2s, then 4s

	raise last or RuntimeError("Intacct gateway call failed.")


def _check_result(root):
	"""Raise on anything Intacct did not accept, with its own error text.

	The decision lives in rules.rejection_errors so it can be tested without a site — it
	is the single point at which a rejected posting is stopped from being recorded as a
	successful one.
	"""
	errors = rules.rejection_errors(root)
	if errors:
		frappe.throw("Intacct rejected the request:\n" + "\n".join(errors))
	return root


# ──────────────────────────────────────────────────────────────────────────────
# Session
# ──────────────────────────────────────────────────────────────────────────────


def entity_for_company(company):
	"""The Intacct entity (locationid) an ERPNext Company posts into.

	One Intacct company holds many entities — E100, E200 and so on. They share one
	credential set; what differs is which entity the session is opened against. Each
	ERPNext Company carries its own, so a transaction's entity is a property of the
	company it belongs to rather than a global setting.
	"""
	if not company:
		return settings().entity_id

	entity = frappe.db.get_value("Company", company, "custom_intacct_entity_id")
	if not entity:
		frappe.throw(
			f"Company {company} has no Intacct Entity ID. "
			"Set it on the Company — every gateway login and every transaction line needs it."
		)
	return entity


def login(entity_id=None, company=None, force=False):
	"""Return a gateway session id for one entity, reusing a cached one where possible.

	The login carries <locationid>. Manufacturing transaction definitions are set to
	"Entity only", so a top-level session is rejected with BL01001973.

	Sessions are cached per entity, not globally: a session opened against E100 cannot
	post into E200.
	"""
	cfg = settings()
	_require_enabled(cfg)

	entity_id = entity_id or entity_for_company(company) or cfg.entity_id

	cache_key = f"{cfg.company_id}:{entity_id or ''}"
	cached = _session_cache.get(cache_key)
	if cached and not force and (time.time() - cached[1]) < SESSION_LIFE_SECONDS:
		return cached[0]

	request = ET.Element("request")
	request.append(_control(cfg))
	operation = ET.SubElement(request, "operation")
	authentication = ET.SubElement(operation, "authentication")
	login_el = ET.SubElement(authentication, "login")
	ET.SubElement(login_el, "userid").text = cfg.user_id
	ET.SubElement(login_el, "companyid").text = cfg.company_id
	ET.SubElement(login_el, "password").text = cfg.get_password("user_password")
	if entity_id:
		ET.SubElement(login_el, "locationid").text = entity_id

	content = ET.SubElement(operation, "content")
	function = ET.SubElement(content, "function", {"controlid": str(uuid.uuid4())})
	ET.SubElement(function, "getAPISession")

	root = _check_result(_post(cfg, request))
	session_id = root.findtext(".//sessionid")
	if not session_id:
		frappe.throw("Intacct login succeeded but returned no session id.")

	_session_cache[cache_key] = (session_id, time.time())
	return session_id


def _request_with_session(cfg, session_id):
	request = ET.Element("request")
	request.append(_control(cfg))
	operation = ET.SubElement(request, "operation")
	authentication = ET.SubElement(operation, "authentication")
	ET.SubElement(authentication, "sessionid").text = session_id
	content = ET.SubElement(operation, "content")
	return request, content


# ──────────────────────────────────────────────────────────────────────────────
# Reads
# ──────────────────────────────────────────────────────────────────────────────


def query(object_name, fields, filter_xml=None, page_size=None, entity_id=None, company=None):
	"""Read every row of an Intacct object, paging until exhausted.

	Ordered by RECORDNO, always. Without an explicit order Intacct returns rows in any
	order, so offset pages overlap AND leave gaps — a donor item sync reported 2362 rows
	from a master of 2000. RECORDNO is unique and immutable on every object.

	`filter_xml` is passed through verbatim as the contents of <filter>, e.g.
	    "<greaterthanorequalto><field>WHENMODIFIED</field><value>...</value></greaterthanorequalto>"
	Passing raw XML rather than wrapping it in a query builder keeps this module flat
	and lets the caller express exactly what Intacct documents.

	Returns a list of Element, one per record.
	"""
	cfg = settings()
	_require_enabled(cfg)
	session_id = login(entity_id=entity_id, company=company)
	# Hard ceiling regardless of what Settings says. Intacct's guidance is UNDER ~1000;
	# a mis-set field must not be able to push past it.
	size = min(page_size or cfg.page_size or 500, 1000)

	rows = []
	offset = 0

	while True:
		request, content = _request_with_session(cfg, session_id)
		function = ET.SubElement(content, "function", {"controlid": str(uuid.uuid4())})
		query_el = ET.SubElement(function, "query")
		ET.SubElement(query_el, "object").text = object_name

		select_el = ET.SubElement(query_el, "select")
		for field in fields:
			ET.SubElement(select_el, "field").text = field

		if filter_xml:
			filter_el = ET.SubElement(query_el, "filter")
			filter_el.append(ET.fromstring(f"<wrap>{filter_xml}</wrap>")[0])

		orderby = ET.SubElement(query_el, "orderby")
		order = ET.SubElement(orderby, "order")
		ET.SubElement(order, "field").text = "RECORDNO"
		ET.SubElement(order, "ascending")

		ET.SubElement(query_el, "pagesize").text = str(size)
		ET.SubElement(query_el, "offset").text = str(offset)

		try:
			root = _check_result(_post(cfg, request))
		except Exception as exc:
			# Reads are logged only when they FAIL. Logging every successful page would
			# make this table the largest on the site during a masters sync — hundreds
			# of pages of no diagnostic value. A failed read is exactly what you need.
			_log_request(
				function_name=f"query {object_name}",
				control_id=None,
				request_xml=ET.tostring(request, encoding="unicode"),
				response_xml=None,
				status="Failed",
				error=str(exc),
				entity_id=entity_id,
			)
			raise

		data = root.find(".//data")
		if data is None:
			break

		page = list(data)
		rows.extend(page)

		remaining = int(data.get("numremaining") or 0)
		if not page or remaining <= 0:
			break
		offset += len(page)

	return rows


@frappe.whitelist()
def lookup(object_name, company=None):
	"""Read an Intacct object's schema — its fields and their types.

	Design-time only, never a data path. This is how you find out what an object
	actually carries instead of guessing field names and getting a rejection back.
	"""
	cfg = settings()
	_require_enabled(cfg)
	session_id = login(company=company)

	request, content = _request_with_session(cfg, session_id)
	function = ET.SubElement(content, "function", {"controlid": str(uuid.uuid4())})
	lookup_el = ET.SubElement(function, "lookup")
	ET.SubElement(lookup_el, "object").text = object_name

	root = _check_result(_post(cfg, request))
	return {
		"fields": [
			{
				"id": field.findtext("ID"),
				"label": field.findtext("LABEL"),
				"type": field.findtext("DATATYPE"),
			}
			for field in root.iter("Field")
		],
		"relationships": [
			{
				"object": rel.findtext("OBJECTNAME"),
				"label": rel.findtext("LABEL"),
				"path": rel.findtext("RELATEDBY"),
			}
			for rel in root.iter("Relationship")
		],
	}


def execute(function_element, entity_id=None, company=None, reference=None, purpose=""):
	"""Post ONE write function and return the affected key.

	`reference` is (doctype, name) of the ERPNext document this posting belongs to. It
	drives the deterministic control ID and ties the log entry back to the document, so
	pass it for anything real.
	"""
	return execute_many(
		[function_element], entity_id=entity_id, company=company, reference=reference, purpose=purpose
	)[0]


def execute_many(function_elements, entity_id=None, company=None, reference=None, purpose="",
                 atomic=True):
	"""Post several write functions as ONE unit of work.

	`atomic=True` wraps them in <operation transaction="true"> so Intacct commits all of
	them or none. This is what closes the partial-failure hole the donor lived with: a
	put-away posted its Out leg, and if the In leg failed the stock had left the bay and
	arrived nowhere, with only a message telling someone to go and fix it by hand.

	Every leg of one movement belongs in a single call. Do not post legs separately and
	hope.
	"""
	if not function_elements:
		return []

	# A write with no reference gets a random control ID and no replay protection —
	# a silent downgrade of the one safeguard that stops duplicate stock. Required, not
	# optional: if a posting has no ERPNext document behind it, that is the bug.
	if not reference or len(reference) != 2 or not all(reference):
		frappe.throw(
			"execute_many needs reference=(doctype, name) — the ERPNext document this "
			"posting belongs to. It drives the deterministic control ID that makes a "
			"replay safe, and ties the request log back to the document."
		)

	cfg = settings()
	_require_enabled(cfg)
	entity = entity_id or entity_for_company(company)
	session_id = login(entity_id=entity, company=company)

	control_id = control_id_for(reference[0], reference[1], purpose)

	request = ET.Element("request")
	# uniqueid=true is what makes the deterministic control ID mean anything: Intacct
	# refuses a second request carrying a control ID it has already processed.
	request.append(_control(cfg, control_id=control_id, unique=True))
	operation = ET.SubElement(request, "operation")
	if atomic and len(function_elements) > 1:
		operation.set("transaction", "true")
	authentication = ET.SubElement(operation, "authentication")
	ET.SubElement(authentication, "sessionid").text = session_id
	content = ET.SubElement(operation, "content")

	names = []
	for index, function_element in enumerate(function_elements, start=1):
		function_element.set("controlid", f"{control_id}-{index}")
		content.append(function_element)
		names.append(next(iter(function_element), ET.Element("?")).tag)

	function_name = ",".join(sorted(set(names)))[:140]
	started = time.time()

	try:
		root = _check_result(_post(cfg, request, retry=False))
	except Exception as exc:
		_log_request(
			function_name=function_name,
			control_id=control_id,
			request_xml=ET.tostring(request, encoding="unicode"),
			response_xml=None,
			status="Failed",
			duration_ms=int((time.time() - started) * 1000),
			error=str(exc),
			reference=reference,
			entity_id=entity,
		)
		raise

	keys = rules.result_keys(root)
	if len(keys) < len(function_elements):
		# Pad rather than let positions shift: caller indexes these against the functions
		# it sent, and a silently shortened list would attribute one function's key to
		# another.
		keys = keys + [None] * (len(function_elements) - len(keys))

	_log_request(
		function_name=function_name,
		control_id=control_id,
		request_xml=ET.tostring(request, encoding="unicode"),
		response_xml=ET.tostring(root, encoding="unicode"),
		status="Success",
		duration_ms=int((time.time() - started) * 1000),
		reference=reference,
		entity_id=entity,
		intacct_key=keys[0] if keys else None,
	)
	return keys


# ──────────────────────────────────────────────────────────────────────────────
# Helpers for reading values off a returned record
# ──────────────────────────────────────────────────────────────────────────────


def val(element, field):
	text = element.findtext(field)
	return text.strip() if text else None


def flag(element, field):
	"""Intacct returns booleans as the strings "true"/"false"."""
	return (val(element, field) or "").lower() == "true"


def number(element, field, default=None):
	from frappe.utils import flt

	text = val(element, field)
	return flt(text) if text else default
