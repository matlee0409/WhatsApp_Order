import unittest

import nlu


MENU = [
    {"name": "Jollof Rice", "price": 2500, "available": True},
    {"name": "Coke", "price": 400, "available": True},
]


class DeterministicParserTests(unittest.TestCase):
    def test_matches_quantities_and_items(self):
        result = nlu.parse_order("2 jollof rice and a coke", MENU)
        self.assertEqual(result["confidence"], "high")
        self.assertEqual([item["quantity"] for item in result["items"]], [2, 1])
        self.assertEqual(result["total"], 5400)

    def test_rejects_unknown_items(self):
        result = nlu.parse_order("one pizza", MENU)
        self.assertEqual(result["confidence"], "low")

    def test_rejects_absurd_quantities(self):
        result = nlu.parse_order("51 coke", MENU)
        self.assertEqual(result["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
