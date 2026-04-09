import unittest
from unittest.mock import patch

from api.tasks import (
    RegisterTaskRequest,
    _build_codex_account_from_result,
    _create_task_record,
    _run_register,
    _task_store,
)
from core.base_mailbox import BaseMailbox, MailboxAccount
from core.base_platform import Account, BasePlatform


class _FakeMailbox(BaseMailbox):
    def get_email(self) -> MailboxAccount:
        return MailboxAccount(email="demo@example.com")

    def get_current_ids(self, account: MailboxAccount) -> set:
        return set()

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set = None,
        code_pattern: str = None,
        **kwargs,
    ) -> str:
        def poll_once():
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=0.01,
            poll_once=poll_once,
        )


class _FakePlatform(BasePlatform):
    name = "fake"
    display_name = "Fake"

    def __init__(self, config=None, mailbox=None):
        super().__init__(config)
        self.mailbox = mailbox

    def register(self, email: str, password: str = None) -> Account:
        account = self.mailbox.get_email()
        self.mailbox.wait_for_code(account, timeout=1)
        return Account(
            platform="fake",
            email=account.email,
            password=password or "pw",
        )

    def check_valid(self, account: Account) -> bool:
        return True


class RegisterTaskControlFlowTests(unittest.TestCase):
    def _build_request(self):
        return RegisterTaskRequest(
            platform="fake",
            count=1,
            concurrency=1,
            proxy="http://proxy.local:8080",
            extra={"mail_provider": "fake"},
        )

    def _run_with_control(self, task_id: str, *, stop: bool = False, skip: bool = False):
        req = self._build_request()
        _create_task_record(task_id, req, "manual", None)
        if stop:
            _task_store.request_stop(task_id)
        if skip:
            _task_store.request_skip_current(task_id)

        with (
            patch("core.registry.get", return_value=_FakePlatform),
            patch("core.base_mailbox.create_mailbox", return_value=_FakeMailbox()),
            patch("core.db.save_account", side_effect=lambda account: account),
            patch("api.tasks._save_task_log"),
        ):
            _run_register(task_id, req)

        return _task_store.snapshot(task_id)

    def test_skip_current_marks_attempt_as_skipped(self):
        snapshot = self._run_with_control("task-control-skip", skip=True)

        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(snapshot["success"], 0)
        self.assertEqual(snapshot["skipped"], 1)
        self.assertEqual(snapshot["errors"], [])

    def test_stop_marks_task_as_stopped(self):
        snapshot = self._run_with_control("task-control-stop", stop=True)

        self.assertEqual(snapshot["status"], "stopped")
        self.assertEqual(snapshot["success"], 0)
        self.assertEqual(snapshot["skipped"], 0)
        self.assertEqual(snapshot["errors"], [])


class CodexPersistenceTests(unittest.TestCase):
    def test_build_codex_account_uses_sub2api_tokens(self):
        account = _build_codex_account_from_result(
            {
                "email": "codex@example.com",
                "password": "pw-123",
                "detail": {
                    "bind": {
                        "target": "sub2api",
                        "status": "success",
                        "message": "Sub2API OAuth 绑定成功",
                        "account_id": "sub2api-acc-1",
                        "sync_state": {"status": "success", "remote_state": "access_token_valid"},
                        "persist_response": {
                            "credentials": {
                                "access_token": "access-1",
                                "refresh_token": "refresh-1",
                                "id_token": "id-1",
                                "chatgpt_account_id": "workspace-1",
                                "chatgpt_user_id": "user-1",
                                "organization_id": "org-1",
                                "client_id": "client-1",
                                "workspace_id": "workspace-1",
                            }
                        },
                    }
                },
            }
        )

        self.assertEqual(account.platform, "codex")
        self.assertEqual(account.email, "codex@example.com")
        self.assertEqual(account.password, "pw-123")
        self.assertEqual(account.token, "access-1")
        self.assertEqual(account.user_id, "workspace-1")
        self.assertEqual(account.extra["access_token"], "access-1")
        self.assertEqual(account.extra["refresh_token"], "refresh-1")
        self.assertEqual(account.extra["id_token"], "id-1")
        self.assertEqual(account.extra["workspace_id"], "workspace-1")
        self.assertEqual(account.extra["sub2api_account_id"], "sub2api-acc-1")
        self.assertEqual(account.extra["sync_statuses"]["sub2api"]["status"], "success")

    def test_build_codex_account_accepts_sparse_cpa_result(self):
        account = _build_codex_account_from_result(
            {
                "email": "cpa@example.com",
                "password": "pw-456",
                "detail": {
                    "bind": {
                        "target": "cpa",
                        "status": "success",
                        "message": "CPA 绑定成功",
                    }
                },
            }
        )

        self.assertEqual(account.platform, "codex")
        self.assertEqual(account.email, "cpa@example.com")
        self.assertEqual(account.password, "pw-456")
        self.assertEqual(account.token, "")
        self.assertEqual(account.extra["refresh_token"], "")
        self.assertEqual(account.extra["codex_bind_target"], "cpa")
        self.assertEqual(account.extra["codex_bind_status"], "success")

    def test_run_register_persists_codex_account(self):
        req = RegisterTaskRequest(
            platform="codex",
            count=1,
            concurrency=1,
            proxy="http://proxy.local:8080",
            extra={"mail_provider": "gmail_alias", "mailbox_service_id": 3},
        )
        task_id = "task-codex-persist"
        _create_task_record(task_id, req, "manual", None)
        saved_accounts = []

        codex_result = {
            "email": "persist@example.com",
            "password": "pw-789",
            "detail": {
                "bind": {
                    "target": "sub2api",
                    "status": "success",
                    "persist_response": {
                        "credentials": {
                            "access_token": "access-2",
                            "refresh_token": "refresh-2",
                            "chatgpt_account_id": "workspace-2",
                        }
                    },
                }
            },
        }

        with (
            patch("core.registry.get", return_value=_FakePlatform),
            patch("core.base_mailbox.create_mailbox", return_value=_FakeMailbox()),
            patch("api.tasks._run_codex_via_original_scripts", return_value=codex_result),
            patch("core.db.save_account", side_effect=lambda account: saved_accounts.append(account) or account),
            patch("api.tasks._save_task_log") as mock_save_task_log,
            patch("services.external_sync.sync_account", return_value=[]),
        ):
            _run_register(task_id, req)

        self.assertEqual(len(saved_accounts), 1)
        saved = saved_accounts[0]
        self.assertEqual(saved.platform, "codex")
        self.assertEqual(saved.email, "persist@example.com")
        self.assertEqual(saved.password, "pw-789")
        self.assertEqual(saved.token, "access-2")
        self.assertEqual(saved.user_id, "workspace-2")
        self.assertEqual(saved.extra["refresh_token"], "refresh-2")
        self.assertEqual(saved.extra["access_token"], "access-2")
        self.assertEqual(saved.extra["mail_provider"], "gmail_alias")
        self.assertEqual(saved.extra["mailbox_service_id"], 3)
        mock_save_task_log.assert_called_once()
        log_args = mock_save_task_log.call_args.args
        log_kwargs = mock_save_task_log.call_args.kwargs
        self.assertEqual(log_args[0], "codex")
        self.assertEqual(log_args[1], "persist@example.com")
        self.assertEqual(log_args[2], "success")
        self.assertEqual(log_kwargs["detail"], codex_result)


if __name__ == "__main__":
    unittest.main()
