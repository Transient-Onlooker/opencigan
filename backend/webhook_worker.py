"""Explicitly started worker for the opt-in webhook queue."""

import os
import signal
import threading

from backend.webhook_delivery import send_webhook
from backend.webhook_store import WebhookStore


def deliver_next(store, now=None, sender=send_webhook):
    delivery = store.claim(now=now)
    if delivery is None:
        return False
    try:
        result = sender(delivery["destination"], delivery["body"], delivery["signing_secret"], delivery["event_id"])
    except ValueError:
        result = {"delivered": False, "retryable": False, "status": None, "retryAfter": None}
    store.finish(delivery["id"], delivery["leaseToken"], result, now=now)
    return True


def run_worker(store, stop_event):
    while not stop_event.is_set():
        if not deliver_next(store):
            stop_event.wait(2)


def main():
    path = os.environ.get("OPENCIGAN_HISTORY_DB", "").strip()
    if os.environ.get("OPENCIGAN_WEBHOOKS_ENABLED") != "1" or not path or not os.path.isfile(path):
        raise SystemExit("Webhook worker requires an enabled feature and an existing history database")
    stop_event = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop_event.set())
    run_worker(WebhookStore(path), stop_event)


if __name__ == "__main__":
    main()
