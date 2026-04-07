import unittest

from services.hotmail_accounts import _normalize_hotmail_mail


class HotmailAccountsTests(unittest.TestCase):
    def test_normalize_hotmail_mail_keeps_message_id_stable_across_graph_and_relay(self):
        raw_id = "AQMkExampleMessage"

        graph_item = {
            "id": raw_id,
            "subject": "Your ChatGPT code is 123456",
            "receivedDateTime": "2026-04-06T13:05:19Z",
        }
        relay_item = {
            "message_id": raw_id,
            "subject": "Your ChatGPT code is 123456",
            "date": "2026-04-06T13:05:19Z",
        }

        graph_mail = _normalize_hotmail_mail(graph_item, "INBOX")
        relay_mail = _normalize_hotmail_mail(relay_item, "INBOX")

        self.assertEqual(graph_mail["message_id"], "graph:inbox:AQMkExampleMessage")
        self.assertEqual(relay_mail["message_id"], "graph:inbox:AQMkExampleMessage")


if __name__ == "__main__":
    unittest.main()
