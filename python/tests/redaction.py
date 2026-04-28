from src.gantry.engine import *
from src.gantry.schema import *
import unittest
import random


class TestDataRedaction(unittest.TestCase):
    def setUp(self):
        self.policy = load_policy(
            {
                "name": "test_data_redaction",
                "redact": {
                    "full": ["password", "secret"],
                    "partial": ["email", "credit_card"],
                    "hashed": ["user_id"],
                },
            }
        )

    def test_full_redaction(self):
        data = {"password": "this-is-a-password", "secret": "hidden-key"}
        redacted = redact_dict(data, self.policy)
        self.assertEqual(redacted["password"], "***")
        self.assertEqual(redacted["secret"], "***")

    def test_partial_redaction(self):
        data = {"email": "alice@example.com"}
        redacted = redact_dict(data, self.policy)

        # ------------------------------------
        # "al***" (first 2 chars kept)
        # ------------------------------------
        self.assertEqual(redacted["email"], "al***")

    def test_hashed_redaction(self):
        data = {"user_id": "12345"}
        redacted = redact_dict(data, self.policy)
        # ------------------------------------
        # Should be a hex string of length 8
        # ------------------------------------
        self.assertEqual(len(redacted["user_id"]), 8)
        self.assertNotEqual(redacted["user_id"], "12345")

    def test_nested_redaction(self):
        data = {
            "user": {
                "password": "nested-password",
                "profile": {"email": "bob@example.com"},
            },
            "list": [{"secret": "item-secret"}],
        }
        redacted = redact_dict(data, self.policy)
        self.assertEqual(redacted["user"]["password"], "***")
        self.assertEqual(redacted["user"]["profile"]["email"], "bo***")
        self.assertEqual(redacted["list"][0]["secret"], "***")

    def test_no_redaction_fast_path(self):
        empty_policy = load_policy({"name": "empty"})
        data = {"key": "value"}
        redacted = redact_dict(data, empty_policy)
        self.assertEqual(redacted, data)


if __name__ == "__main__":
    unittest.main()
