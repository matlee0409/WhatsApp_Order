import unittest

import interactive


class InteractiveReplyTests(unittest.TestCase):
    def test_parses_snake_case_list_reply_id(self):
        self.assertEqual(
            interactive.parse_reply({"list_reply": {"id": "category:Drinks"}}),
            "category:Drinks",
        )

    def test_parses_camel_case_button_reply_payload(self):
        self.assertEqual(
            interactive.parse_reply({"buttonReply": {"payload": "DONE"}}),
            "DONE",
        )

    def test_prefers_interactive_metadata_id(self):
        self.assertEqual(
            interactive.parse_reply({"metadata": {"interactiveId": "YES"}}),
            "YES",
        )

    def test_ignores_malformed_interaction(self):
        self.assertEqual(interactive.parse_reply({"list_reply": "DONE"}), "")

    def test_builds_native_catalog_product_list(self):
        payload = interactive.catalog_product_list(
            "catalog-id",
            [("Burgers", [{"retailer_id": "menu-item-4"}])],
        )
        self.assertEqual(payload["type"], "product_list")
        self.assertEqual(payload["action"]["catalog_id"], "catalog-id")
        self.assertEqual(
            payload["action"]["sections"][0]["product_items"],
            [{"product_retailer_id": "menu-item-4"}],
        )


if __name__ == "__main__":
    unittest.main()
