"""One delivery step for the opt-in webhook queue."""

from backend.webhook_delivery import send_webhook


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
