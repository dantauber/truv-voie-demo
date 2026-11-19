# Cedar & Stone Bank: Truv income verification in a loan application

A working prototype of a bank's personal loan application with Truv income and employment verification (VOIE) built into the flow. The borrower fills in the application, connects their payroll account in Truv Bridge without leaving the page, and the bank gets verified employer, income and paystub data plus a VOIE report. It uses Truv Embedded Orders and was built as a case study for a Truv Solutions Architect role, modeled on the Truv and nCino integration. Cedar & Stone Bank is fictional and the app runs against the Truv sandbox.

## Live demo

https://truv-voie-demo.onrender.com

The demo runs on Render's free tier, which sleeps after about 15 minutes idle. The first load can take about a minute while it wakes up.

Sandbox login inside Truv Bridge:

1. Pick any payroll provider (for example ADP) or "Truv Payroll Provider".
2. Username `goodlogin`, password `goodpassword`.
3. If asked for a verification code, enter `12345`.

## How the integration works

1. **Create the order.** When the borrower submits "About you", the server calls `POST /v1/orders/` with `products: ["income"]` and stores the order `id`, `user_id` and `bridge_token`.
2. **Launch Truv Bridge at the VOIE step.** The page loads `https://cdn.truv.com/bridge.js` and calls `TruvBridge.init` with `isOrder: true` and the order's `bridge_token`. The borrower finds their employer and logs in to payroll.
3. **Advance on completion.** The page moves on only when Bridge sends `onEvent` with type `COMPLETED` and source `order`.
4. **Webhooks.** Truv posts `task-status-updated`, `order-status-updated` and `order-finalized` to `/webhooks/truv`. The server checks the `X-WEBHOOK-SIGN` HMAC-SHA256 signature and matches each event to the application by `user_id`.
5. **Results.** The review page calls `GET /v1/orders/{order_id}/` on the server and shows employer, job title, income and recent paystubs. The VOIE report is available as JSON and PDF.

A "Behind the scenes" panel on each page shows the API calls, Bridge events and webhooks for the current application as they happen.

## Run locally

Prerequisites: Python 3.13, [uv](https://docs.astral.sh/uv/), and Truv sandbox keys from the Truv Dashboard (Development, API Keys).

```bash
uv venv
uv pip install -r requirements.txt
cp .env.example .env    # then fill in TRUV_CLIENT_ID and TRUV_SECRET
.venv/bin/gunicorn app:app --workers 1 --threads 8 --bind 127.0.0.1:5050
```

Open http://127.0.0.1:5050. Keep one worker: applications are held in memory.

All Truv API calls are outbound, so everything except webhooks works locally. To receive webhooks locally, expose the app with a tunnel such as ngrok and register `https://<tunnel>/webhooks/truv` with Truv.

| Variable | Required | Purpose |
|---|---|---|
| `TRUV_CLIENT_ID` | Yes | Truv client ID |
| `TRUV_SECRET` | Yes | Truv access secret. Also verifies webhook signatures. Never commit or log it. |
| `TRUV_BASE_URL` | No | Default `https://prod.truv.com/v1`. Sandbox or production is decided by the keys. |
| `BANK_NAME` | No | Default "Cedar & Stone Bank" |

## Documentation

- [Solution Design Document (PDF)](docs/Truv_VOIE_Solution_Design.pdf): assumptions, workflow, APIs in call order, webhooks, success criteria and QA checklist. A Word version is in the same folder.
- [DOCUMENTATION.md](DOCUMENTATION.md): technical reference for this prototype.
- [Postman collection](postman/): every call in flow order with real sandbox example responses. Import the collection and the `Truv Sandbox` environment, then add your sandbox keys to the environment's current values.

## Deploy on Render

`render.yaml` defines one free web service. Connect the repo in Render, enter `TRUV_CLIENT_ID` and `TRUV_SECRET` when asked, and every push to `main` deploys. Then register `https://<your-service>.onrender.com/webhooks/truv` with Truv for the three events above.

## Limits of the prototype

State is kept in memory and in `data/store.json`, which Render's free disk wipes on restart. One gunicorn worker is used on purpose. A production build would use a database and run more than one instance. See the Solution Design Document, Appendix C.
