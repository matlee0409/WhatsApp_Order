"""Pickup-ready polling (Section 8).

Run on a schedule every 2-3 minutes (cron on Linux, Task Scheduler on Windows).
This is the ENTIRE pickup mechanism — there is no Telegram command and no
Telegram inbound webhook. The owner just changes an order's Status cell to
"Ready"; this script notices and notifies the customer.

For each order with Status == Ready and Ready Notified != Yes, it sends the
pickup WhatsApp and then sets Ready Notified = Yes so it never double-notifies.
On a send failure it logs + alerts admin and does NOT set the flag, so the order
retries on the next run (Section 8 step 4). reminders.py only ever writes the
Ready Notified column (Section 12.6).
"""

import config
import sheets
import whatsapp
from logger import get_logger, redact_phone
from notifier import notify_admin

log = get_logger("reminders")


def check_ready_orders():
    """One polling pass. Returns the number of customers successfully notified."""
    try:
        ready = sheets.get_ready_orders()
    except Exception as exc:
        log.error("Failed to read Orders sheet: %s", exc)
        notify_admin(f"reminders.py could not read the Orders sheet: {exc}")
        return 0

    notified = 0
    for _row_num, rec in ready:
        order_ref = rec["order_ref"]
        phone = rec["phone"]
        name = rec["name"] or "there"

        message = (
            f"Hi {name}, your order {order_ref} is ready for pickup!\n"
            f"Pickup address: {config.PICKUP_ADDRESS}\n"
            "See you soon."
        )

        sent = whatsapp.send_whatsapp(phone, message)
        if not sent:
            # Do NOT mark notified — let it retry next run (Section 8 step 4).
            log.error("Pickup WhatsApp failed for %s (%s)",
                      order_ref, redact_phone(phone))
            notify_admin(
                f"Failed to send pickup notification for {order_ref}. "
                "Will retry next run."
            )
            continue

        try:
            # Success only: stamp Ready At (J) and set Ready Notified (K).
            sheets.set_ready_notified(order_ref, ready_at=sheets._now_iso())
        except Exception as exc:
            log.error("Sent pickup for %s but failed to set Ready Notified: %s",
                      order_ref, exc)
            notify_admin(
                f"Pickup sent for {order_ref} but Ready Notified update failed: "
                f"{exc}. May double-notify next run."
            )
            continue

        # Log with redacted phone, traced by order reference (Section 12.7).
        log.info("Notified pickup for order %s (%s)",
                 order_ref, redact_phone(phone))
        notified += 1

    return notified


if __name__ == "__main__":
    count = check_ready_orders()
    log.info("reminders.py run complete — %d customer(s) notified", count)
