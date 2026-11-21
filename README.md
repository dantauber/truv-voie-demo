# Cedar & Stone Bank: Truv income verification in a loan application

A working prototype of a bank's personal loan application with Truv income and employment verification (VOIE) built into the flow. The borrower fills in the application, connects their payroll account in Truv Bridge without leaving the page, and the bank gets verified employer, income and paystub data plus a VOIE report. It uses Truv Embedded Orders and was built as a case study for a Truv Solutions Architect role, modeled on the Truv and nCino integration. Cedar & Stone Bank is fictional and the app runs against the Truv sandbox.

## Live demo

https://truv-voie-demo.onrender.com

The demo runs on Render's free tier, which sleeps after about 15 minutes idle. The first load can take about a minute while it wakes up.

The site asks for a user name and password first. They are shared with reviewers separately.

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

Open http://127.0.0.1:5050. Keep one worker: with the default file store, applications are held in memory.

All Truv API calls are outbound, so everything except webhooks works locally. To receive webhooks locally, expose the app with a tunnel such as ngrok and register `https://<tunnel>/webhooks/truv` with Truv.

| Variable | Required | Purpose |
|---|---|---|
| `TRUV_CLIENT_ID` | Yes | Truv client ID |
| `TRUV_SECRET` | Yes | Truv access secret. Also verifies webhook signatures. Never commit or log it. |
| `TRUV_BASE_URL` | No | Default `https://prod.truv.com/v1`. Sandbox or production is decided by the keys. |
| `BANK_NAME` | No | Default "Cedar & Stone Bank" |
| `DEMO_USER`, `DEMO_PASSWORD` | No | Site login (HTTP Basic Auth). When both are set, every page asks for them except `/webhooks/truv` (protected by the Truv signature check) and `/health`. Leave empty to turn the login off. |
| `STORE_BACKEND` | No | `file` (default): memory plus `data/store.json`. `dynamodb`: a DynamoDB table, used on AWS Lambda. |
| `DYNAMODB_TABLE` | With `dynamodb` | Table name. Set by the Lambda template. |
| `SAVE_SAMPLES` | No | Default `1`: save real Truv payloads to `samples/`. Set to `0` on read-only disks (Lambda). |

Locally, all of these go in `.env`. On Render and Lambda they are set in the platform, never in the repo.

## Documentation

- [Solution Design Document (PDF)](docs/Truv_VOIE_Solution_Design.pdf): assumptions, workflow, APIs in call order, webhooks, success criteria and QA checklist. A Word version is in the same folder.
- [DOCUMENTATION.md](DOCUMENTATION.md): technical reference for this prototype.
- [Postman collection](postman/): every call in flow order with real sandbox example responses. Import the collection and the `Truv Sandbox` environment, then add your sandbox keys to the environment's current values.

## Deployment

The same code runs on Render and on AWS Lambda. Only environment variables differ:

| | Render | AWS Lambda |
|---|---|---|
| Runs as | One always-on gunicorn process | Function started on demand, gunicorn behind the AWS Lambda Web Adapter |
| Storage | `file` (memory plus `data/store.json`) | `dynamodb` (table created by the template) |
| Idle behavior | Free tier sleeps after about 15 minutes, about a minute to wake | Cold start of a second or two, no sleep |
| Config | `render.yaml` | `deploy/lambda/template.yaml` and `Makefile` |

Truv sends webhooks to one URL. Register the URL of the platform you are demoing.

### Deploy on Render

`render.yaml` defines one free web service (Python 3.13 from `.python-version`, gunicorn with one worker, health check on `/health`).

1. In Render, choose New, Blueprint, and connect this repository.
2. Enter `TRUV_CLIENT_ID`, `TRUV_SECRET`, `DEMO_USER` and `DEMO_PASSWORD` when asked. Leave the last two empty to turn the login off.
3. Every push to `main` deploys.
4. Register `https://<your-service>.onrender.com/webhooks/truv` with Truv for `order-status-updated`, `task-status-updated` and `order-finalized`.

For a service created before the login was added, Render does not prompt again. Add `DEMO_USER` and `DEMO_PASSWORD` under the service's Environment tab.

The free service sleeps after about 15 minutes idle. To keep it awake, ping `https://<your-service>.onrender.com/health` every 5 minutes with an uptime monitor such as UptimeRobot, and open the site a minute before a demo.

### Deploy on AWS Lambda

`deploy/lambda/template.yaml` is an AWS SAM template. It creates:

- A Python 3.13 Lambda function that runs the same gunicorn command as Render, through the [AWS Lambda Web Adapter](https://github.com/aws/aws-lambda-web-adapter) layer.
- A public Function URL (HTTPS). The app's own login protects the pages.
- A DynamoDB table (on-demand billing) for applications, with a `user_id` index for webhook matching.

Prerequisites: an AWS account, the [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) signed in (`aws configure` or `aws sso login`), the [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html), and uv. Docker is not needed: the `Makefile` downloads Linux wheels with uv and copies only the app files, so `.env`, `.venv`, `data/` and `samples/` are never uploaded.

From the repository root:

```bash
sam build --template-file deploy/lambda/template.yaml --build-in-source
sam deploy --guided
```

The guided deploy asks for a stack name (for example `truv-voie-demo`), a region, and the parameters `TruvClientId`, `TruvSecret`, `DemoUser` and `DemoPassword`. If it asks whether a function URL without authentication is okay, answer yes: the app handles the login. It saves your answers to `samconfig.toml`, which is in `.gitignore`. Later deploys need only `sam build ... && sam deploy`.

The stack outputs `SiteUrl` and `WebhookUrl`. Register `WebhookUrl` with Truv for the three events above.

Logs (including the `WEBHOOK_SAMPLE` lines) go to CloudWatch:

```bash
sam logs --stack-name truv-voie-demo --tail
```

To remove everything, including the table: `sam delete --stack-name truv-voie-demo`.

Cost at demo traffic is within the AWS free tier for Lambda and DynamoDB. The Web Adapter layer version is a template parameter (`WebAdapterLayerVersion`); check the project page for the latest.

## Limits of the prototype

On Render, state is kept in memory and in `data/store.json`, which Render's free disk wipes on restart, so one gunicorn worker is used on purpose. On Lambda, state is in DynamoDB and survives restarts, but each application is one item, and DynamoDB caps an item at 400 KB, which is plenty for a demo. A production build would also add retention rules, encryption settings and monitoring. See the Solution Design Document, Appendix C.
