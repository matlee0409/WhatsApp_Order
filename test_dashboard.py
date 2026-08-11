import unittest
import unittest
from unittest.mock import MagicMock, patch

import app as app_module


class DashboardAccessTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret", SESSION_COOKIE_SECURE=False)
        self.client = app_module.app.test_client()
        self.password_patch = patch.object(app_module.config, "DASHBOARD_PASSWORD", "strong-test-password")
        self.password_patch.start()
        app_module._login_rate._hits.clear()

    def tearDown(self):
        self.password_patch.stop()

    def login(self, **extra):
        return self.client.post(
            "/dashboard/login",
            data={"password": "strong-test-password", **extra},
            follow_redirects=False,
        )

    def test_protected_page_redirects_to_login(self):
        response = self.client.get("/dashboard/orders")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard/login", response.headers["Location"])

    def test_valid_login_opens_dashboard(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/dashboard/orders"))
        page = self.client.get("/dashboard/orders")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Order command center", page.data)

    def test_invalid_login_is_generic(self):
        response = self.client.post("/dashboard/login", data={"password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"not correct", response.data)
        self.assertNotIn(b"strong-test-password", response.data)

    def test_external_redirect_is_rejected(self):
        response = self.login(next="https://attacker.example/collect")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("attacker.example", response.headers["Location"])

    def test_logout_clears_session(self):
        self.login()
        response = self.client.post("/dashboard/logout")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/dashboard/orders").status_code, 302)

    def test_health_and_webhooks_remain_public(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        # Missing signatures are rejected by the webhook itself, not dashboard auth.
        self.assertEqual(self.client.post("/zernio/webhook").status_code, 403)
        self.assertEqual(self.client.post("/paystack/webhook", data=b"{}").status_code, 401)

    def test_production_requires_persistent_webhook_and_flask_secrets(self):
        with patch.object(app_module.config, "FLASK_ENV", "production"), \
             patch.object(app_module.config, "PAYSTACK_SECRET_KEY", "sk_live_test"), \
             patch.object(app_module.config, "DATABASE_URL", "postgresql+psycopg://db"), \
             patch.object(app_module.config, "REDIS_URL", "redis://redis"), \
             patch.object(app_module.config, "FLASK_SECRET_KEY", None), \
             patch.object(app_module.config, "ZERNIO_WEBHOOK_SECRET", None):
            with self.assertRaisesRegex(RuntimeError, "FLASK_SECRET_KEY"):
                app_module.config.check_production_safety()

            app_module.config.FLASK_SECRET_KEY = "persistent-flask-secret"
            with self.assertRaisesRegex(RuntimeError, "ZERNIO_WEBHOOK_SECRET"):
                app_module.config.check_production_safety()

            app_module.config.ZERNIO_WEBHOOK_SECRET = "<Generate Value>"
            with self.assertRaisesRegex(RuntimeError, "example placeholder"):
                app_module.config.check_production_safety()

    @patch.object(app_module.zernio, "send_message")
    @patch.object(app_module, "interactive_payload", return_value=None)
    @patch.object(app_module, "handle_message", return_value="Hello")
    @patch.object(app_module.zernio, "remember_conversation")
    @patch.object(app_module.zernio, "verify_webhook_signature", return_value=True)
    def test_zernio_webhook_handles_documented_message_payload(
        self, verify, remember, handle, payload, send
    ):
        response = self.client.post(
            "/zernio/webhook",
            json={
                "event": "message.received",
                "data": {
                    "sender": {"phone": "+15551234567"},
                    "accountId": "account-id",
                    "conversationId": "conversation-id",
                    "message": {"text": "hi"},
                },
            },
            headers={"X-Zernio-Signature": "signature"},
        )
        self.assertEqual(response.status_code, 200)
        remember.assert_called_once_with("+15551234567", "account-id", "conversation-id")
        handle.assert_called_once_with("+15551234567", "hi")
        send.assert_called_once_with("account-id", "conversation-id", "Hello", None)

    def test_zernio_connection_requires_dashboard_login(self):
        response = self.client.get("/dashboard/zernio/connect")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/dashboard/login", response.headers["Location"])

    @patch.object(app_module.config, "ZERNIO_API_KEY", "test-api-key")
    @patch.object(app_module.config, "ZERNIO_PROFILE_ID", "test-profile")
    @patch.object(app_module.config, "ZERNIO_REDIRECT_URI", "https://example.test/dashboard/zernio/callback")
    @patch.object(app_module.zernio.requests, "post")
    @patch.object(app_module.zernio.requests, "get")
    def test_zernio_connection_redirects_to_hosted_signup(self, get, post):
        profiles = MagicMock()
        profiles.json.return_value = {"profiles": []}
        profiles.raise_for_status.return_value = None
        auth = MagicMock()
        auth.json.return_value = {"data": {"authUrl": "https://zernio.example/signup"}}
        auth.raise_for_status.return_value = None
        get.side_effect = [profiles, auth]
        post.return_value.json.return_value = {"profile": {"_id": "profile-created"}}
        post.return_value.raise_for_status.return_value = None
        self.login()
        response = self.client.get("/dashboard/zernio/connect")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://zernio.example/signup")
        with self.client.session_transaction() as session:
            self.assertTrue(session.get("zernio_oauth_state"))
        self.assertEqual(get.call_count, 2)
        post.assert_called_once()

    def test_zernio_callback_rejects_invalid_state(self):
        self.login()
        response = self.client.get("/dashboard/zernio/callback?state=wrong&connected=whatsapp&accountId=account")
        self.assertEqual(response.status_code, 302)
        self.assertIn("zernio_error=invalid_state", response.headers["Location"])

    def test_zernio_callback_stores_non_sensitive_connection_details(self):
        self.login()
        with self.client.session_transaction() as session:
            session["zernio_oauth_state"] = "expected-state"
        response = self.client.get(
            "/dashboard/zernio/callback?state=expected-state&connected=whatsapp"
            "&profileId=profile&accountId=account&username=%2B2348000000000"
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["zernio_connection"]["account_id"], "account")
            self.assertEqual(session["zernio_connection"]["phone"], "+2348000000000")
            self.assertNotIn("api_key", session["zernio_connection"])

    def test_zernio_documented_callback_without_state_connects(self):
        self.login()
        with self.client.session_transaction() as session:
            session["zernio_oauth_state"] = "provider-does-not-return-state"
        response = self.client.get(
            "/dashboard/zernio/callback?connected=whatsapp"
            "&profileId=profile&accountId=account&username=%2B2348000000000"
        )
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertEqual(session["zernio_connection"]["account_id"], "account")


if __name__ == "__main__":
    unittest.main()
