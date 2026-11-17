"""Cedar & Stone Bank: demo personal loan application with Truv income verification.

Flow:
  1. Borrower fills in the application (/apply).
  2. Server creates a Truv order (POST /v1/orders/) and keeps bridge_token, id, user_id.
  3. Browser opens Truv Bridge with isOrder: true and the order's bridge_token.
  4. Browser advances only on onEvent COMPLETED with source "order".
  5. Server fetches results (GET /v1/orders/{id}/) for the review page.
  6. Truv webhooks (order-status-updated, task-status-updated) arrive at
     /webhooks/truv, are signature checked, and are matched to the order by user_id.
"""

import hashlib
import hmac
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

load_dotenv()

TRUV_BASE_URL = os.environ.get("TRUV_BASE_URL", "https://prod.truv.com/v1")
TRUV_CLIENT_ID = os.environ.get("TRUV_CLIENT_ID", "")
TRUV_SECRET = os.environ.get("TRUV_SECRET", "")
BANK_NAME = os.environ.get("BANK_NAME", "Cedar & Stone Bank")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SAMPLES_DIR = BASE_DIR / "samples"
STORE_FILE = DATA_DIR / "store.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bank")

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Storage: in-memory, mirrored to a JSON file. Enough for a single-worker demo.
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_store = {"applications": {}, "user_index": {}, "unmatched_webhooks": []}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load_store():
    global _store
    if STORE_FILE.exists():
        try:
            _store = json.loads(STORE_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            log.warning("Could not read %s, starting empty", STORE_FILE)


def _save_store():
    DATA_DIR.mkdir(exist_ok=True)
    STORE_FILE.write_text(json.dumps(_store, indent=2))


def _add_event(order_id, kind, label, detail=None):
    """Record a step in the application's timeline (shown in the developer panel)."""
    with _lock:
        appl = _store["applications"].get(order_id)
        if appl is None:
            return
        appl["timeline"].append({"at": _now(), "kind": kind, "label": label, "detail": detail})
        _save_store()


def _get_application(order_id):
    with _lock:
        appl = _store["applications"].get(order_id)
        return json.loads(json.dumps(appl)) if appl else None


def _save_sample(name, body):
    """Save a real Truv payload for the Postman collection and the design doc."""
    SAMPLES_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (SAMPLES_DIR / f"{stamp}_{name}.json").write_text(json.dumps(body, indent=2))


_load_store()


# ---------------------------------------------------------------------------
# Truv API client (server side only, the secret never reaches the browser)
# ---------------------------------------------------------------------------

class TruvError(Exception):
    pass


def _truv_headers():
    if not TRUV_CLIENT_ID or not TRUV_SECRET:
        raise TruvError("TRUV_CLIENT_ID and TRUV_SECRET must be set")
    return {
        "X-Access-Client-Id": TRUV_CLIENT_ID,
        "X-Access-Secret": TRUV_SECRET,
        "Content-Type": "application/json",
    }


def truv_create_order(first_name, last_name, email=None):
    payload = {"products": ["income"], "first_name": first_name, "last_name": last_name}
    if email:
        payload["email"] = email
    resp = requests.post(f"{TRUV_BASE_URL}/orders/", json=payload, headers=_truv_headers(), timeout=20)
    if resp.status_code not in (200, 201):
        log.error("Create order failed: HTTP %s %s", resp.status_code, resp.text[:500])
        raise TruvError(f"Create order failed (HTTP {resp.status_code})")
    return resp.json()


def truv_get_order(order_id):
    resp = requests.get(f"{TRUV_BASE_URL}/orders/{order_id}/", headers=_truv_headers(), timeout=20)
    if resp.status_code != 200:
        log.error("Get order failed: HTTP %s %s", resp.status_code, resp.text[:500])
        raise TruvError(f"Get order failed (HTTP {resp.status_code})")
    return resp.json()


# ---------------------------------------------------------------------------
# Security headers. CSP allows only what Truv Bridge needs.
# ---------------------------------------------------------------------------

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://cdn.truv.com",
    "frame-src https://my.truv.com https://cdn.truv.com https://prod.truv.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "connect-src 'self' https://*.truv.com",
    "font-src 'self' data:",
])


@app.after_request
def add_security_headers(resp):
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resp


@app.context_processor
def inject_globals():
    return {"bank_name": BANK_NAME, "year": datetime.now().year}


# ---------------------------------------------------------------------------
# Borrower pages
# ---------------------------------------------------------------------------

LOAN_PURPOSES = [
    "Debt consolidation",
    "Home improvement",
    "Major purchase",
    "Medical expenses",
    "Moving or relocation",
    "Other",
]


@app.get("/")
def home():
    return render_template("home.html")


@app.get("/apply")
def apply_form():
    return render_template("apply.html", purposes=LOAN_PURPOSES, form={}, error=None)


@app.post("/apply")
def apply_submit():
    form = {k: (request.form.get(k) or "").strip() for k in
            ("first_name", "last_name", "email", "phone", "amount", "term", "purpose")}

    missing = [k for k in ("first_name", "last_name", "email", "amount", "term", "purpose") if not form[k]]
    if missing:
        return render_template("apply.html", purposes=LOAN_PURPOSES, form=form,
                               error="Please complete all required fields."), 400
    try:
        amount = int(form["amount"].replace(",", "").replace("$", ""))
        if not 1000 <= amount <= 50000:
            raise ValueError
    except ValueError:
        return render_template("apply.html", purposes=LOAN_PURPOSES, form=form,
                               error="Loan amount must be between $1,000 and $50,000."), 400

    try:
        order = truv_create_order(form["first_name"], form["last_name"], form["email"])
    except (TruvError, requests.RequestException) as exc:
        log.error("Could not create Truv order: %s", exc)
        return render_template("apply.html", purposes=LOAN_PURPOSES, form=form,
                               error="We could not start income verification. Please try again."), 502

    _save_sample("create_order_response", order)
    order_id = order["id"]
    with _lock:
        _store["applications"][order_id] = {
            "order_id": order_id,
            "user_id": order["user_id"],
            "bridge_token": order["bridge_token"],
            "applicant": {k: form[k] for k in ("first_name", "last_name", "email", "phone")},
            "loan": {"amount": amount, "term": form["term"], "purpose": form["purpose"]},
            "status": "verification_pending",
            "order_status": None,
            "created_at": _now(),
            "timeline": [],
            "webhooks": [],
        }
        _store["user_index"][order["user_id"]] = order_id
        _save_store()

    log.info("Created Truv order %s for user %s", order_id, order["user_id"])
    _add_event(order_id, "api", "POST /v1/orders/ returned 201",
               {"id": order_id, "user_id": order["user_id"], "products": order.get("products")})
    return redirect(url_for("verify", order_id=order_id))


@app.get("/apply/<order_id>/verify")
def verify(order_id):
    appl = _get_application(order_id) or abort(404)
    if appl["status"] == "verified":
        return redirect(url_for("review", order_id=order_id))
    return render_template("verify.html", appl=appl)


@app.post("/apply/<order_id>/bridge-event")
def bridge_event(order_id):
    """The browser reports Bridge events here so they show in the timeline.

    The server never trusts these to mark the application verified. It confirms by
    calling GET /v1/orders/{id}/ when the review page loads.
    """
    appl = _get_application(order_id) or abort(404)
    data = request.get_json(silent=True) or {}
    event_type = str(data.get("type", ""))[:50]
    source = str(data.get("source", ""))[:50]
    _add_event(order_id, "bridge", f"Bridge onEvent {event_type}" + (f" (source: {source})" if source else ""))
    if event_type == "COMPLETED" and source == "order" and appl["status"] != "verified":
        with _lock:
            _store["applications"][order_id]["status"] = "bridge_completed"
            _save_store()
    return jsonify(ok=True)


@app.get("/apply/<order_id>/review")
def review(order_id):
    appl = _get_application(order_id) or abort(404)
    try:
        order = truv_get_order(order_id)
    except (TruvError, requests.RequestException) as exc:
        log.error("Could not fetch Truv order %s: %s", order_id, exc)
        return render_template("review.html", appl=appl, summary=None, order=None,
                               error="We could not load your verified income. Please refresh in a moment."), 502

    _save_sample("get_order_response", order)
    summary = summarize_order(order)
    _add_event(order_id, "api", "GET /v1/orders/{id}/ returned 200",
               {"employers": len(order.get("employers") or []), "verified": summary["verified"]})
    if summary["verified"]:
        with _lock:
            _store["applications"][order_id]["status"] = "verified"
            _save_store()
        appl["status"] = "verified"
    return render_template("review.html", appl=appl, summary=summary, order=order, error=None)


@app.post("/apply/<order_id>/submit")
def submit(order_id):
    appl = _get_application(order_id) or abort(404)
    with _lock:
        _store["applications"][order_id]["status"] = "submitted"
        _store["applications"][order_id]["submitted_at"] = _now()
        _save_store()
    _add_event(order_id, "app", "Application submitted to underwriting")
    return redirect(url_for("submitted", order_id=order_id))


@app.get("/apply/<order_id>/submitted")
def submitted(order_id):
    appl = _get_application(order_id) or abort(404)
    return render_template("submitted.html", appl=appl)


@app.get("/apply/<order_id>/timeline")
def timeline(order_id):
    """Polled by the developer panel to show API calls, Bridge events and webhooks live."""
    appl = _get_application(order_id) or abort(404)
    return jsonify(status=appl["status"], order_status=appl.get("order_status"),
                   order_finalized=appl.get("order_finalized", False), timeline=appl["timeline"])


# ---------------------------------------------------------------------------
# Order summary: turn the Truv order into what a loan officer needs to see.
# ---------------------------------------------------------------------------

def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize_order(order):
    employments = []
    for employer in order.get("employers") or []:
        for emp in employer.get("employments") or []:
            company = emp.get("company") or {}
            statements = sorted(emp.get("statements") or [], key=lambda s: s.get("pay_date") or "", reverse=True)
            employments.append({
                "company": company.get("name") or employer.get("company_name") or "Employer",
                "job_title": emp.get("job_title"),
                "job_type": emp.get("job_type"),
                "is_active": emp.get("is_active"),
                "start_date": emp.get("start_date"),
                "end_date": emp.get("end_date"),
                "income": _num(emp.get("income")),
                "income_unit": emp.get("income_unit"),
                "pay_rate": _num(emp.get("pay_rate")),
                "pay_frequency": emp.get("pay_frequency"),
                "statements": [{
                    "pay_date": s.get("pay_date"),
                    "period_start": s.get("period_start"),
                    "period_end": s.get("period_end"),
                    "gross_pay": _num(s.get("gross_pay")),
                    "net_pay": _num(s.get("net_pay")),
                    "hours": _num(s.get("hours")),
                } for s in statements[:6]],
                "annual": [{
                    "year": a.get("year"),
                    "gross_pay": _num(a.get("gross_pay")),
                } for a in sorted(emp.get("annual_income_summary") or [],
                                  key=lambda a: a.get("year") or 0, reverse=True)],
            })
    employer_status = [e.get("status") or "pending" for e in order.get("employers") or []]
    return {
        "verified": bool(employments) or bool(order.get("completed_at")),
        "completed_at": order.get("completed_at"),
        "employer_status": employer_status,
        "employments": employments,
        "pdf_reports": [e.get("pdf_report") for e in order.get("employers") or [] if e.get("pdf_report")],
    }


@app.template_filter("money")
def money(value):
    if value is None:
        return "Not reported"
    return f"${value:,.2f}"


@app.template_filter("pretty")
def pretty(value):
    if not value:
        return "Not reported"
    return str(value).replace("_", " ").capitalize()


# ---------------------------------------------------------------------------
# Truv webhooks
# ---------------------------------------------------------------------------

def verify_webhook_signature(raw_body, header_value):
    """X-WEBHOOK-SIGN is "v1=" + hex HMAC-SHA256 of the raw body, keyed with the access secret."""
    if not header_value or not TRUV_SECRET:
        return False
    expected = "v1=" + hmac.new(TRUV_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value.strip())


@app.post("/webhooks/truv")
def truv_webhook():
    raw = request.get_data()  # raw bytes, before any JSON parsing
    if not verify_webhook_signature(raw, request.headers.get("X-WEBHOOK-SIGN")):
        log.warning("Rejected webhook with missing or invalid signature")
        return jsonify(error="invalid signature"), 401

    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify(error="invalid json"), 400

    event_type = event.get("event_type")
    user_id = event.get("user_id")
    _save_sample(f"webhook_{event_type or 'unknown'}", event)
    # Render's disk is ephemeral, so also log the payload as one line to copy from the logs.
    # Webhook bodies carry IDs and statuses only, no credentials.
    log.info("WEBHOOK_SAMPLE %s", json.dumps(event, separators=(",", ":")))

    with _lock:
        order_id = _store["user_index"].get(user_id)
        if order_id is None:
            _store["unmatched_webhooks"].append({"at": _now(), "event": event})
            _store["unmatched_webhooks"] = _store["unmatched_webhooks"][-50:]
            _save_store()
            log.info("Webhook %s for unknown user_id %s stored as unmatched", event_type, user_id)
            return jsonify(ok=True)
        appl = _store["applications"][order_id]
        appl["webhooks"].append(event)
        if event_type == "order-status-updated" and event.get("status"):
            appl["order_status"] = event["status"]
        elif event_type == "order-finalized":
            # The whole order is terminal: no more data collection or refresh.
            appl["order_finalized"] = True
        _save_store()

    status = event.get("status")
    log.info("Webhook %s status=%s matched to order %s", event_type, status, order_id)
    _add_event(order_id, "webhook", f"Webhook {event_type}" + (f": {status}" if status else ""),
               {k: event.get(k) for k in ("webhook_id", "status", "product", "data_source") if event.get(k)})
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Ops
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return jsonify(status="ok")


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", message="We could not find that application."), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
