"""Application storage with two backends, chosen by the STORE_BACKEND environment variable.

- file (default): a dict in memory, mirrored to data/store.json. Used locally and on Render.
  Needs a single process (one gunicorn worker), because the dict is not shared.
- dynamodb: one DynamoDB table keyed by order_id, with a user_id index for webhook matching.
  Used on AWS Lambda, where each request can run in a different container.

Both backends have the same methods, so app.py does not know which one is running.
"""

import copy
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

log = logging.getLogger("bank")

UNMATCHED_LIMIT = 50                    # file backend keeps the last 50 unmatched webhooks
UNMATCHED_TTL_SECONDS = 7 * 24 * 3600   # dynamodb backend expires them after 7 days


def _now():
    return datetime.now(timezone.utc).isoformat()


class FileStore:
    def __init__(self, path):
        self._path = Path(path)
        self._lock = threading.Lock()
        self._data = {"applications": {}, "user_index": {}, "unmatched_webhooks": []}
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (OSError, json.JSONDecodeError):
                log.warning("Could not read %s, starting empty", self._path)

    def _save(self):
        self._path.parent.mkdir(exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2))

    def create_application(self, appl):
        with self._lock:
            self._data["applications"][appl["order_id"]] = copy.deepcopy(appl)
            self._data["user_index"][appl["user_id"]] = appl["order_id"]
            self._save()

    def get_application(self, order_id):
        with self._lock:
            appl = self._data["applications"].get(order_id)
            return copy.deepcopy(appl) if appl else None

    def update_fields(self, order_id, **fields):
        with self._lock:
            appl = self._data["applications"].get(order_id)
            if appl is None:
                return False
            appl.update(fields)
            self._save()
            return True

    def append_event(self, order_id, event):
        with self._lock:
            appl = self._data["applications"].get(order_id)
            if appl is None:
                return
            appl["timeline"].append(event)
            self._save()

    def apply_webhook(self, user_id, event, fields):
        """Attach a webhook to its application. Returns the order_id, or None if unmatched."""
        with self._lock:
            order_id = self._data["user_index"].get(user_id)
            if order_id is None or order_id not in self._data["applications"]:
                unmatched = self._data["unmatched_webhooks"]
                unmatched.append({"at": _now(), "event": event})
                self._data["unmatched_webhooks"] = unmatched[-UNMATCHED_LIMIT:]
                self._save()
                return None
            appl = self._data["applications"][order_id]
            appl["webhooks"].append(event)
            appl.update(fields)
            self._save()
            return order_id


def _to_dynamo(value):
    """boto3 rejects Python floats, so store numbers as Decimal."""
    return json.loads(json.dumps(value), parse_float=Decimal)


def _from_dynamo(value):
    if isinstance(value, list):
        return [_from_dynamo(v) for v in value]
    if isinstance(value, dict):
        return {k: _from_dynamo(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


class DynamoStore:
    USER_INDEX = "user_id-index"

    def __init__(self, table_name):
        import boto3  # only needed for this backend
        from boto3.dynamodb.conditions import Key

        self._table = boto3.resource("dynamodb").Table(table_name)
        self._key = Key
        self._conditional_failed = self._table.meta.client.exceptions.ConditionalCheckFailedException

    def create_application(self, appl):
        self._table.put_item(Item=_to_dynamo(appl))

    def get_application(self, order_id):
        item = self._table.get_item(Key={"order_id": order_id}, ConsistentRead=True).get("Item")
        return _from_dynamo(item) if item else None

    def _update(self, order_id, set_fields, append=None):
        """SET each field, and optionally append items to list attributes, in one atomic write."""
        parts, names, values = [], {}, {}
        for i, (name, value) in enumerate(set_fields.items()):
            names[f"#f{i}"] = name
            values[f":v{i}"] = _to_dynamo(value)
            parts.append(f"#f{i} = :v{i}")
        for i, (name, item) in enumerate((append or {}).items()):
            names[f"#l{i}"] = name
            values[f":l{i}"] = [_to_dynamo(item)]
            values[":empty"] = []
            parts.append(f"#l{i} = list_append(if_not_exists(#l{i}, :empty), :l{i})")
        if not parts:
            return True
        try:
            self._table.update_item(
                Key={"order_id": order_id},
                UpdateExpression="SET " + ", ".join(parts),
                ConditionExpression="attribute_exists(order_id)",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
            return True
        except self._conditional_failed:
            return False

    def update_fields(self, order_id, **fields):
        return self._update(order_id, fields)

    def append_event(self, order_id, event):
        self._update(order_id, {}, {"timeline": event})

    def apply_webhook(self, user_id, event, fields):
        order_id = None
        if user_id:
            # Index reads are eventually consistent. Truv webhooks follow borrower actions in
            # Bridge, seconds after the order was stored, so the index is current by then.
            resp = self._table.query(IndexName=self.USER_INDEX,
                                     KeyConditionExpression=self._key("user_id").eq(user_id), Limit=1)
            items = resp.get("Items") or []
            order_id = items[0]["order_id"] if items else None
        if order_id and self._update(order_id, fields, {"webhooks": event}):
            return order_id
        self._table.put_item(Item=_to_dynamo({
            "order_id": f"unmatched#{_now()}#{uuid.uuid4().hex[:8]}",
            "at": _now(),
            "event": event,
            "ttl": int(time.time()) + UNMATCHED_TTL_SECONDS,
        }))
        return None


def get_store(default_file):
    backend = os.environ.get("STORE_BACKEND", "file").strip().lower()
    if backend == "dynamodb":
        table = os.environ.get("DYNAMODB_TABLE", "").strip()
        if not table:
            raise RuntimeError("STORE_BACKEND=dynamodb needs DYNAMODB_TABLE")
        log.info("Using DynamoDB store (table %s)", table)
        return DynamoStore(table)
    if backend != "file":
        raise RuntimeError(f"Unknown STORE_BACKEND {backend!r}, use file or dynamodb")
    log.info("Using file store (%s)", default_file)
    return FileStore(default_file)
