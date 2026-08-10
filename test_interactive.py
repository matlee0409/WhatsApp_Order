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


if __name__ == "__main__":
    unittest.main()
