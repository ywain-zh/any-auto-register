import unittest
from unittest.mock import patch

from services.hotmail_accounts import (
    HOTMAIL_MAILBOX_STATUS_INVALID,
    HOTMAIL_MAILBOX_STATUS_UNKNOWN,
    HOTMAIL_MODE_GRAPH,
    HOTMAIL_MODE_IMAP,
    _normalize_hotmail_mail,
    _parse_hotmail_line,
    classify_hotmail_mailbox_error,
    refresh_hotmail_token,
)


class HotmailAccountsTests(unittest.TestCase):
    def test_parse_hotmail_line_defaults_mode_to_graph_for_legacy_format(self):
        parsed = _parse_hotmail_line(
            "demo@outlook.com----mailbox-pass----client-id----refresh-token"
        )

        self.assertEqual(
            parsed,
            {
                "email": "demo@outlook.com",
                "mailbox_password": "mailbox-pass",
                "client_id": "client-id",
                "refresh_token": "refresh-token",
                "receive_mode": HOTMAIL_MODE_GRAPH,
            },
        )

    def test_parse_hotmail_line_accepts_explicit_imap_mode(self):
        parsed = _parse_hotmail_line(
            "demo@outlook.com----mailbox-pass----client-id----refresh-token----imap"
        )

        self.assertEqual(parsed["receive_mode"], HOTMAIL_MODE_IMAP)

    def test_parse_hotmail_line_rejects_invalid_mode(self):
        parsed = _parse_hotmail_line(
            "demo@outlook.com----mailbox-pass----client-id----refresh-token----pop3"
        )

        self.assertIsNone(parsed)

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

    def test_normalize_hotmail_mail_prefixes_imap_message_id(self):
        imap_item = {
            "Id": "OutlookMessageId",
            "Subject": "Your ChatGPT code is 654321",
            "DateTimeReceived": "2026-04-06T13:05:19Z",
        }

        mail = _normalize_hotmail_mail(imap_item, "INBOX", HOTMAIL_MODE_IMAP)

        self.assertEqual(mail["message_id"], "imap:inbox:OutlookMessageId")
        self.assertEqual(mail["subject"], "Your ChatGPT code is 654321")

    def test_classify_hotmail_mailbox_error_marks_invalid_for_token_errors(self):
        status = classify_hotmail_mailbox_error(
            "failed to refresh token: invalid_grant: refresh_token is invalid"
        )

        self.assertEqual(status, HOTMAIL_MAILBOX_STATUS_INVALID)

    def test_classify_hotmail_mailbox_error_keeps_unknown_for_transient_errors(self):
        status = classify_hotmail_mailbox_error(
            "microsoft token endpoint request failed: httpsconnectionpool read timed out"
        )

        self.assertEqual(status, HOTMAIL_MAILBOX_STATUS_UNKNOWN)

    @patch("services.hotmail_accounts._get_graph_access_token")
    def test_refresh_hotmail_token_uses_graph_mode_by_default(self, mock_graph_token):
        mock_graph_token.return_value = {
            "access_token": "access-graph",
            "refresh_token": "refresh-graph",
            "token_url": "https://graph.example/token",
            "scope": "graph-scope",
        }

        result = refresh_hotmail_token(
            client_id="client-id",
            refresh_token="refresh-token",
        )

        mock_graph_token.assert_called_once_with(
            client_id="client-id",
            refresh_token="refresh-token",
        )
        self.assertEqual(result["receive_mode"], HOTMAIL_MODE_GRAPH)
        self.assertEqual(result["refresh_token"], "refresh-graph")

    @patch("services.hotmail_accounts._get_imap_access_token")
    def test_refresh_hotmail_token_uses_imap_mode(self, mock_imap_token):
        mock_imap_token.return_value = {
            "access_token": "access-imap",
            "refresh_token": "refresh-imap",
            "token_url": "https://imap.example/token",
            "scope": "imap-scope",
        }

        result = refresh_hotmail_token(
            client_id="client-id",
            refresh_token="refresh-token",
            receive_mode=HOTMAIL_MODE_IMAP,
        )

        mock_imap_token.assert_called_once_with(
            client_id="client-id",
            refresh_token="refresh-token",
        )
        self.assertEqual(result["receive_mode"], HOTMAIL_MODE_IMAP)
        self.assertEqual(result["refresh_token"], "refresh-imap")

    @patch("services.hotmail_accounts._get_graph_access_token")
    def test_refresh_hotmail_token_falls_back_to_graph_for_invalid_mode(self, mock_graph_token):
        mock_graph_token.return_value = {
            "access_token": "access-graph",
            "refresh_token": "refresh-graph",
            "token_url": "https://graph.example/token",
            "scope": "graph-scope",
        }

        result = refresh_hotmail_token(
            client_id="client-id",
            refresh_token="refresh-token",
            receive_mode="pop3",
        )

        mock_graph_token.assert_called_once_with(
            client_id="client-id",
            refresh_token="refresh-token",
        )
        self.assertEqual(result["receive_mode"], HOTMAIL_MODE_GRAPH)


if __name__ == "__main__":
    unittest.main()
