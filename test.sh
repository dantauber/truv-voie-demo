#!/bin/zsh

SCRIPT_DIR="${0:A:h}"
set -a
source "$SCRIPT_DIR/.env"
set +a
: "${TRUV_CLIENT_ID:?TRUV_CLIENT_ID not set in .env}"
: "${TRUV_SECRET:?TRUV_SECRET not set in .env}"

curl -sS -X POST https://prod.truv.com/v1/orders/ \
  -H "X-Access-Client-Id: $TRUV_CLIENT_ID" \
  -H "X-Access-Secret: $TRUV_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"products":["income"],"first_name":"Test","last_name":"Borrower"}'
