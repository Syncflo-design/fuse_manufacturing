"""Sage Intacct XML gateway.

Everything that talks to Intacct goes through here. One module, no class hierarchy:
a session, a query, a post.

Why XML and not REST: REST forces every customer through app registration in the Sage
developer portal. The gateway needs only a sender ID plus company credentials.

The constraints encoded below were learned the hard way on the donor app. See
docs/02-intacct-integration.md before changing any of them.
"""

import time
import uuid
import xml.etree.ElementTree as ET

import frappe
import requests

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


def _control(cfg, unique=False):
	"""The <control> block every request carries."""
	control = ET.Element("control")
	ET.SubElement(control, "senderid").text = cfg.sender_id
	ET.SubElement(control, "password").text = cfg.get_password("sender_password")
	ET.SubElement(control, "controlid").text = str(uuid.uuid4())
	ET.SubElement(control, "uniqueid").text = "true" if unique else "false"
	ET.SubElement(control, "dtdversion").text = "3.0"
	return control


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


def _post(cfg, request_element):
	"""POST one <request> and return the parsed response root.

	Retries transient failures with backoff. A single dropped connection in a
	several-hundred-call import must not fail the whole run.
	"""
	body = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(request_element, encoding="utf-8")
	attempts = cfg.max_attempts or 3
	last = None

	for attempt in range(1, attempts + 1):
		try:
			response = requests.post(
				cfg.gateway_url,
				data=body,
				headers={"Content-Type": "application/xml"},
				timeout=cfg.timeout or 300,
			)
			if response.status_code >= 500 or response.status_code == 429:
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
	"""Raise on any failure Intacct reports, with its own error text.

	Intacct returns HTTP 200 for business rejections, so the status has to be read out
	of the body or a failed post looks like a success.
	"""
	for status in root.iter("status"):
		if (status.text or "").strip().lower() == "failure":
			errors = []
			for error in root.iter("error"):
				parts = [
					(error.findtext(tag) or "").strip()
					for tag in ("errorno", "description", "description2", "correction")
				]
				errors.append(" | ".join(p for p in parts if p))
			frappe.throw("Intacct rejected the request:\n" + "\n".join(errors or ["no error detail returned"]))
	return root


# ──────────────────────────────────────────────────────────────────────────────
# Session
# ──────────────────────────────────────────────────────────────────────────────


def login(force=False):
	"""Return a gateway session id, reusing a cached one where possible.

	The login carries <locationid>. Manufacturing transaction definitions are set to
	"Entity only", so a top-level session is rejected with BL01001973.
	"""
	cfg = settings()
	_require_enabled(cfg)

	cache_key = f"{cfg.company_id}:{cfg.entity_id or ''}"
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
	if cfg.entity_id:
		ET.SubElement(login_el, "locationid").text = cfg.entity_id

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


def query(object_name, fields, filter_xml=None, page_size=None):
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
	session_id = login()
	size = page_size or cfg.page_size or 1000

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

		root = _check_result(_post(cfg, request))
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


def execute(function_element):
	"""Post one write function (create/update/delete) and return the affected key.

	Deliberately one function per call. Multi-record posts that must succeed or fail
	together need <operation transaction="true"> — add that when a caller genuinely
	needs it, not before.
	"""
	cfg = settings()
	_require_enabled(cfg)
	session_id = login()

	request, content = _request_with_session(cfg, session_id)
	content.append(function_element)

	root = _check_result(_post(cfg, request))
	return root.findtext(".//key")


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
