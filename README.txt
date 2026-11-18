Cedar & Stone Bank: Truv income verification in a loan application
==================================================================

A working prototype of a bank's loan application point-of-sale (POS) with
Truv income and employment verification (VOIE) embedded in the flow. Built
as a case study for a Truv Solutions Architect role, modeled on the Truv and
nCino integration. Cedar & Stone Bank is fictional.

Full documentation: DOCUMENTATION.md


LIVE DEMO
---------
https://truv-voie-demo.onrender.com

The free Render service sleeps after about 15 minutes idle. The first page
load can take 30 to 60 seconds while it wakes up.

Sandbox login inside Truv Bridge:
  1. Pick any payroll provider (for example ADP) or "Truv Payroll Provider"
  2. Username: goodlogin   Password: goodpassword
  3. If asked for a verification code, enter 12345

In the sandbox every provider is simulated, so these test logins work with
any of them. With production keys, only "Truv Payroll Provider" accepts test
logins; real providers such as ADP need real payroll accounts.


WHAT IT DOES
------------
  1. The borrower fills in a loan application.
  2. The server creates a Truv order (POST /v1/orders/).
  3. The browser opens Truv Bridge with the order's bridge token.
  4. The borrower connects their payroll account in Bridge.
  5. The page advances only when Bridge reports COMPLETED from the order.
  6. The server fetches the verified income (GET /v1/orders/{id}/) and shows
     it on the review page.
  7. Truv webhooks arrive at /webhooks/truv, are signature checked, and are
     matched to the application by user_id.

A "Behind the scenes" panel on each page shows the API calls, Bridge events
and webhooks for the current application as they happen.


RUN LOCALLY
-----------
Requirements: Python 3.13 and uv (https://docs.astral.sh/uv/).

  uv venv
  uv pip install -r requirements.txt
  cp .env.example .env          # then fill in TRUV_CLIENT_ID and TRUV_SECRET
  .venv/bin/gunicorn app:app --workers 1 --threads 8 --bind 127.0.0.1:5050

Open http://127.0.0.1:5050

Everything except webhooks works locally, because all Truv API calls are
outbound. Webhooks need a public HTTPS URL, so they are tested on Render.

Quick API check (creates one sandbox order):
  ./test.sh


ENVIRONMENT VARIABLES
---------------------
  TRUV_CLIENT_ID   Truv client ID (required)
  TRUV_SECRET      Truv access secret (required). Also used to verify
                   webhook signatures. Never commit or log it.
  TRUV_BASE_URL    Optional. Default https://prod.truv.com/v1
                   (sandbox or production is decided by the keys)
  BANK_NAME        Optional. Default "Cedar & Stone Bank"


DEPLOY (RENDER)
---------------
render.yaml defines one free web service. Connect the GitHub repo in
Render, enter TRUV_CLIENT_ID and TRUV_SECRET when asked, and every push to
main deploys. Then register the webhook URL with Truv:

  https://<your-service>.onrender.com/webhooks/truv
  events: task-status-updated, order-status-updated, order-finalized


FILES
-----
  app.py              Routes, Truv API client, webhook handler
  templates/          Borrower pages (Jinja)
  static/verify.js    Opens Truv Bridge and handles its events
  static/dev_panel.js "Behind the scenes" timeline
  postman/            Postman collection and environment
  render.yaml         Render service definition
  test.sh             curl check that creates an order
  DOCUMENTATION.md    Architecture, API flow, webhooks, testing, lessons


LIMITS OF THE PROTOTYPE
-----------------------
State is kept in memory and in data/store.json. Render's free disk is wiped
on restart, so applications from earlier sessions disappear there. One
gunicorn worker is used on purpose. A production build would use a
database. See DOCUMENTATION.md, "Production considerations".
