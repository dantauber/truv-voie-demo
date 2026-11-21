#!/bin/sh
# Lambda handler script. The AWS Lambda Web Adapter layer (AWS_LAMBDA_EXEC_WRAPPER=/opt/bootstrap)
# starts this, waits for the app on port 8080, then forwards each Function URL request to it.
# Same gunicorn command as Render. Only /tmp is writable on Lambda.
exec python3 -m gunicorn app:app --workers 1 --threads 8 --timeout 30 \
  --worker-tmp-dir /tmp --bind 0.0.0.0:8080
