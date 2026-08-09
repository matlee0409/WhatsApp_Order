import unittest
from unittest.mock import patch

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
        self.assertEqual(self.client.post("/whatsapp/webhook").status_code, 403)
        self.assertEqual(self.client.post("/paystack/webhook", data=b"{}").status_code, 401)


if __name__ == "__main__":
    unittest.main()
