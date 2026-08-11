# WhatsApp Order Bot

A standalone, Tier‑1 WhatsApp order management agent for restaurants, food
vendors, cloud kitchens, and small retailers. Built by Jorion Technologies and
designed to be cloned and deployed by any developer.

Pickup only. PostgreSQL is the database. The order parser matches customer
messages against the live menu. Paystack handles payment. Telegram notifies the
owner (outbound only).

---

## 1. What it does

End‑to‑end order management, from the customer's first WhatsApp message to the
pickup‑ready notification.

**Customer order flow**

1. Customer texts anything — the bot greets them and shows the menu categories.
2. Customer picks a category — the bot lists items and prices.
3. Customer says what they want in a menu-matching message ("2 jollof and a
   cold Coke") — the parser matches menu items and quantities.
4. The bot adds items to a running **cart**. The customer can browse more
   categories and add from each, then reply **DONE** to check out.
5. The bot shows the full order summary and total. Customer replies **YES**.
6. **First‑time customers** are then asked for a **name** and an **email** for
   the receipt — they can reply **SKIP** to the email step to continue without
   one (it falls back to `BUSINESS_EMAIL`). **Returning customers** (recognised
   by their phone number from a previous order) skip both steps automatically,
   reusing their stored name and email.
7. The bot generates a unique exact‑amount **Paystack** payment link and writes
   a PENDING order to PostgreSQL.
8. Customer pays → Paystack webhook fires → the bot confirms payment over
   WhatsApp, notifies the kitchen via Telegram, and (optionally) emails a
   receipt via Brevo.
9. The owner prepares the order and changes its **Status** to `Ready` in the
   Orders sheet.
10. A polling script (`reminders.py`) detects `Status=Ready` and notifies the
    customer over WhatsApp that the order is ready for pickup — then marks
    `Ready Notified=Yes` so it never double‑notifies.

**Self‑serve status:** a customer can text `ORDER ORD-REF` to get the current
status of their order back.

---

## 2. Prerequisites

- **Python 3.11+**
- **Paystack** account (live secret key + webhook secret)
- **Google Cloud** service account with the Sheets API enabled
  (`credentials.json`)
- **Zernio** account configured for WhatsApp Business
- **Telegram** bot token + admin chat id (outbound notifications only)
- *(optional)* **Brevo** API key for email receipts

---

## 3. PostgreSQL setup

1. Create a Google Cloud project and enable the **PostgreSQL API**.
2. Create a **service account**, generate a JSON key, and save it as
   `credentials.json` in the project root. **Never commit this file** — it is
   already in `.gitignore`.
3. Create one spreadsheet with **two tabs** and **share it with the service
   account email** (Editor access).
4. Put the spreadsheet id (from its URL) into `GOOGLE_SPREADSHEET_ID`.

**Tab 1 — `Menu`** (exact headers, row 1):

| Category | Item Name | Description | Price | Available |
|----------|-----------|-------------|-------|-----------|
| Rice Dishes | Jollof Rice | Smoky party jollof | 2500 | Yes |
| Drinks | Coke | Chilled 50cl | 400 | Yes |

- `Price` is in **Naira** (the bot converts to kobo for Paystack).
- `Available` is `Yes` or `No` — the owner toggles it.

**Tab 2 — `Orders`** (exact headers, row 1):

| Order Reference | Customer Phone | Customer Name | Items | Total Amount | Status | Payment Reference | Created At | Paid At | Ready At | Ready Notified | Email |
|---|---|---|---|---|---|---|---|---|---|---|---|

- `Status` flows: `Pending` → `Paid` → `Ready` → `Collected` (or `Cancelled`).
- The bot manages `Ready Notified` — **the owner never touches column K**.
- **Column L: Email** — customer email (collected at checkout or falls back to
  `BUSINESS_EMAIL`).

---

## 4. How the owner updates the menu

Just edit the **`Menu`** tab. The bot reads the menu **live on every
conversation**, so adding items, changing prices, or toggling `Available`
takes effect immediately — no restart needed.

---

## 5. How the owner marks an order ready

Open the **`Orders`** tab and change that order's **Status** from `Paid` to
`Ready`. The bot's polling script picks it up and sends the customer a pickup
WhatsApp **within 2–3 minutes** (the polling interval). There is no command to
learn — it is one cell edit. The bot then sets `Ready Notified=Yes` so the
customer is notified exactly once.

---

## 6. Paystack setup

1. Use your **live** secret key in `PAYSTACK_SECRET_KEY`.
2. In the Paystack dashboard, set the **webhook URL** to your public
   `https://your-domain/paystack/webhook`.
3. Subscribe to the **`charge.success`** event.
4. Put the webhook secret into `PAYSTACK_WEBHOOK_SECRET`. The bot validates the
   `x-paystack-signature` header (HMAC‑SHA512 of the raw body) and returns
   `401` on mismatch.

---

## 7. Zernio WhatsApp setup

1. Set `ZERNIO_API_KEY` in your environment.
2. Set `ZERNIO_WEBHOOK_SECRET` to the same persistent secret configured in Zernio.
   In Railway, use the variable's **Generate Value** action, then copy that value
   into Zernio's webhook signing-secret setting. Do not generate a new value on
   each deployment or boot.
3. Open the dashboard settings page and use **Connect Facebook & WhatsApp** to
   complete the hosted Zernio/Meta signup flow.
4. Configure Zernio to send signed inbound events to
   `https://your-domain/zernio/webhook` (POST).
5. Configure the webhook signature format expected by `ZERNIO_WEBHOOK_SECRET`.

---

## 8. Configuration

Copy `.env.example` to `.env` and fill in every value. For Railway, create
`FLASK_SECRET_KEY` and `ZERNIO_WEBHOOK_SECRET` with the variable editor's
**Generate Value** action and leave those generated values unchanged across
redeployments. Railway variable references such as `${{ secret() }}` are not
required for this app; the important part is that the values are persistent and
match the corresponding provider configuration. Don't forget:

- `PICKUP_ADDRESS` — shown to customers in confirmation and pickup messages.
- `BUSINESS_NAME` — used in the greeting and receipts.
- `BUSINESS_EMAIL` — your business email used as a fallback when customers skip
  the email step at checkout.

`.env` and `credentials.json` are **gitignored** and must never be committed.

---

## 10. Run

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # then fill it in
python app.py                    # starts Flask on $PORT (default 5003)
```

Expose the app over **HTTPS** with a tunnel (e.g. `ngrok http 5003`) and use
that public URL for the Zernio and Paystack webhooks.

---

## 11. Schedule the pickup poller

`reminders.py` must run every **2–3 minutes** to send pickup notifications.

**Linux/macOS (cron):**

```cron
*/2 * * * * cd /path/to/whatsapp-order-bot && /path/to/.venv/bin/python reminders.py >> logs/reminders.log 2>&1
```

**Windows:** create a Task Scheduler task that runs
`.venv\Scripts\python.exe reminders.py` every 2 minutes.

---

## 12. Security notes

- **Paystack signature** — HMAC‑SHA512 of the raw body, constant‑time compared,
  `401` on mismatch.
- **Zernio signature** — HMAC-SHA256 validated against the raw webhook body,
  `403` on mismatch.
- **Idempotency** — Paystack by payment reference (checked in the Orders sheet).
- **Menu validation** — every parsed item and price is matched against the live
  menu; unavailable or unknown items are rejected.
- **Input validation** — phone numbers must be E.164‑ish, order references are
  alphanumeric + hyphen (max 15 chars), all customer text is untrusted.
- **PII in logs** — phone numbers are redacted (`+234***890`), customer names
  are never logged; trace by Order Reference.
- **Secrets** — all credentials come from environment variables.
  `credentials.json` and `.env` are gitignored and never committed.
- **Flask** — `debug=False` in production, no stack traces in responses, inbound
  webhooks return `200` quickly.
- **Sheets apostrophe stripping** — applied on every read (PostgreSQL
  prepends an apostrophe to values starting with `+` or `=`).

---

## 13. Tier 2 upgrade path

Available from Jorion Technologies:

- Delivery orders with address collection
- Order modification before payment
- Loyalty and repeat‑customer recognition
- Multi‑branch support
- Inventory management and stock alerts
- Web dashboard for order management
- Instant pickup notification (no polling delay)

→ https://joriontech.com/ai-agents

---

## 14. License

MIT — see [LICENSE](LICENSE). © 2026 Jorion Technologies Limited.
