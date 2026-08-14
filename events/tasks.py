# events/tasks.py
import time
import logging
from celery import shared_task

logger = logging.getLogger(__name__)

SUCCESS_CODES = {"COMPLETED", "SUCCESSFUL", "SUCCESS", "PAID", "APPROVED"}
FINAL_FAILURE_CODES = {"FAILED", "CANCELLED", "DECLINED", "VOID"}

@shared_task(bind=True)
def verify_payment_task(self, order_id: str, order_tracking_id: str, attempts: int = 6, backoff: int = 30):
    """
    Recheck a single order `attempts` times with `backoff` seconds between tries.
    On success -> mark paid and book booths (no ticket generation here).
    On final failure -> release reserved booths and mark order failed.
    """
    from .models import Order

    # local import to avoid circular import issues; pesapal_status lives in views in your current code
    try:
        from .views import pesapal_status
    except Exception:
        logger.exception("Could not import pesapal_status from views")
        pesapal_status = None

    try:
        order = Order.objects.get(id=order_id)
    except Order.DoesNotExist:
        logger.error("verify_payment_task: order not found %s", order_id)
        return

    for attempt in range(1, attempts + 1):
        logger.info("verify_payment_task attempt %d/%d for order %s", attempt, attempts, order_id)

        try:
            # call pesapal status helper (this function returns parsed JSON or {'status': 'UNKNOWN'})
            if pesapal_status is None:
                data = {"status": "UNKNOWN"}
            else:
                data = pesapal_status(order_tracking_id, str(order_id)) or {}
        except Exception as exc:
            logger.exception("pesapal_status call failed on attempt %d for order %s: %s", attempt, order_id, exc)
            data = {}

        pay_code = str(
            data.get("payment_status_code")
            or data.get("payment_status")
            or data.get("status")
            or ""
        ).upper()
        pay_desc = str(
            data.get("payment_status_description")
            or data.get("description")
            or ""
        ).upper()

        # defensive: if dict, stringify
        if isinstance(pay_code, dict):
            pay_code = str(pay_code)
        if isinstance(pay_desc, dict):
            pay_desc = str(pay_desc)

        # === Success path ===
        if any(s in pay_code for s in SUCCESS_CODES) or any(s in pay_desc for s in SUCCESS_CODES):
            if not order.is_paid:
                order.is_paid = True
                order.payment_status = "success"
                order.pesapal_tracking_id = order_tracking_id
                order.save()

                # Book booths (if any)
                for booth in order.booths.all():
                    try:
                        booked_user = getattr(order, "user", None)
                        booth.mark_booked(user=(booked_user if booked_user and getattr(booked_user, "is_authenticated", False) else None))
                    except Exception:
                        logger.exception("Failed to mark booth booked for booth id=%s", booth.id)

                logger.info("Order %s reconciled as PAID", order_id)
            else:
                logger.info("verify_payment_task: order %s already is_paid=True", order_id)
            return

        # === Final failure path ===
        if any(f in pay_code for f in FINAL_FAILURE_CODES) or any(f in pay_desc for f in FINAL_FAILURE_CODES):
            if attempt < attempts:
                logger.info("Order %s shows failure (code=%s desc=%s); will retry (%d/%d)", order_id, pay_code, pay_desc, attempt, attempts)
            else:
                order.payment_status = (pay_code or pay_desc or "failed").lower()
                order.save()
                for booth in order.booths.all():
                    try:
                        booth.release_reservation()
                    except Exception:
                        logger.exception("Failed to release reservation for booth id=%s", booth.id)
                logger.info("Order %s final failure after retries", order_id)
                return

        # Not final, not success -> wait then retry (exponential-ish)
        time.sleep(backoff * attempt)

    # exhausted attempts -> leave pending for manual inspection
    logger.warning("verify_payment_task exhausted attempts for order %s; left as pending_verification", order_id)
    order.payment_status = "pending_verification"
    order.save()

@shared_task
def reconcile_pending_orders():
    """
    Sweep task: find orders in pending_verification or pending and schedule verify tasks.
    Run this every 5 minutes via celery beat.
    """
    from .models import Order
    pending_orders = Order.objects.filter(payment_status__in=["pending", "pending_verification"])
    for order in pending_orders:
        tracking_id = getattr(order, "pesapal_tracking_id", None)
        if not tracking_id:
            logger.info("Order %s pending but missing pesapal_tracking_id; skipping", order.id)
            continue
        verify_payment_task.delay(str(order.id), tracking_id, attempts=6, backoff=20)