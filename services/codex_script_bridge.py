from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT_DIR / "codex-pool-manager" / "codex-pool-manager"
OAUTH_SCRIPT = SCRIPT_DIR / "codex_oauth_login.py"
REGISTER_SCRIPT = SCRIPT_DIR / "http_register.py"


def run_original_codex_oauth_bind(
    *,
    email: str,
    password: str,
    cpa_url: str,
    cpa_key: str,
    proxy: str | None,
    headless: bool,
    hotmail_account_record: dict,
) -> dict:
    if not OAUTH_SCRIPT.exists():
        raise RuntimeError(f"未找到原脚本: {OAUTH_SCRIPT}")

    with tempfile.TemporaryDirectory(prefix="codex_bind_") as temp_dir:
        temp_path = Path(temp_dir)
        accounts_file = temp_path / "accounts.txt"
        mail_api_file = temp_path / "mail_api.json"
        hotmail_accounts_file = temp_path / "hotmail_accounts.txt"
        accounts_file.write_text(f"{email}----{password}\n", encoding="utf-8")
        hotmail_accounts_file.write_text(
            "----".join(
                [
                    str(hotmail_account_record.get("email") or ""),
                    str(hotmail_account_record.get("mailbox_password") or ""),
                    str(hotmail_account_record.get("client_id") or ""),
                    str(hotmail_account_record.get("refresh_token") or ""),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        mail_api_file.write_text(
            json.dumps(
                {
                    "provider": "hotmail_api",
                    "url": "https://www.appleemail.top",
                    "accounts_file": str(hotmail_accounts_file),
                    "base_dir": str(SCRIPT_DIR),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        command = [
            "python",
            str(OAUTH_SCRIPT.name),
            "--accounts",
            str(accounts_file),
            "--cpa-url",
            cpa_url,
            "--cpa-key",
            cpa_key,
            "--mail-api",
            str(mail_api_file),
        ]
        if proxy:
            command.extend(["--proxy", proxy])
        if headless:
            pass
        else:
            command.append("--no-headless")

        proc = subprocess.run(
            command,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=1800,
            encoding="utf-8",
            errors="ignore",
            shell=False,
        )

        updated_accounts = accounts_file.read_text(encoding="utf-8", errors="ignore")
        ok = "----done" in updated_accounts and "----fail" not in updated_accounts
        return {
            "ok": ok and proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "accounts_result": updated_accounts,
            "command": command,
        }


def run_original_codex_register(
    *,
    config_path: str,
    hotmail_account_record: dict | None,
    proxy: str | None,
    headless: bool,
) -> dict:
    if not REGISTER_SCRIPT.exists():
        raise RuntimeError(f"未找到原注册脚本: {REGISTER_SCRIPT}")
    with tempfile.TemporaryDirectory(prefix="codex_reg_") as temp_dir:
        temp_path = Path(temp_dir)
        command = [
            "python",
            str(REGISTER_SCRIPT.name),
            "-c",
            str(config_path),
            "--count",
            "1",
        ]
        if hotmail_account_record:
            account_file = temp_path / "hotmail_account.txt"
            account_file.write_text(
                "----".join(
                    [
                        str(hotmail_account_record.get("email") or ""),
                        str(hotmail_account_record.get("mailbox_password") or ""),
                        str(hotmail_account_record.get("client_id") or ""),
                        str(hotmail_account_record.get("refresh_token") or ""),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            command.extend(["--account-file", str(account_file)])
        if proxy:
            command.extend(["--proxy", proxy])
        if not headless:
            command.append("--no-headless")
        proc = subprocess.run(
            command,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=1800,
            encoding="utf-8",
            errors="ignore",
            shell=False,
        )
    reg_file = SCRIPT_DIR / "registered_accounts.txt"
    last_line = ""
    if reg_file.exists():
        lines = reg_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        if lines:
            last_line = lines[-1]
    parts = last_line.split("----") if last_line else []
    line_email = parts[0].strip() if len(parts) >= 1 else ""
    line_ok = len(parts) >= 3 and parts[2].strip() == "ok"
    expected_email = (
        str((hotmail_account_record or {}).get("email") or "").strip().lower()
    )
    return {
        "ok": bool(
            line_ok and (not expected_email or line_email.lower() == expected_email)
        ),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "last_registered_line": last_line,
        "command": command,
    }
