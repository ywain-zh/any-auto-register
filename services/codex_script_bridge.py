from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from curl_cffi import requests as cffi_requests


ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT_DIR / "codex-pool-manager" / "codex-pool-manager"
OAUTH_SCRIPT = SCRIPT_DIR / "codex_oauth_login.py"
REGISTER_SCRIPT = SCRIPT_DIR / "http_register.py"


def _python_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def _format_structured_log(prefix: str, line: str) -> str:
    text = line.strip()
    if not text:
        return ""

    text = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", text)
    text = re.sub(r"^\s+", "", text)

    replacements = [
        ("获取 session", "[HTTP][SESSION] 获取 session"),
        ("session 请求", "[HTTP][SESSION] 请求 session"),
        ("chatgpt 响应", "[HTTP][SESSION] chatgpt 响应"),
        ("获取 csrf", "[HTTP][CSRF] 获取 csrf"),
        ("csrf 响应", "[HTTP][CSRF] csrf 响应"),
        ("发起注册", "[HTTP][SIGNUP] 发起注册"),
        ("获取 sentinel tokens", "[BROWSER][SENTINEL] 获取 sentinel tokens"),
        ("获取 register sentinel", "[BROWSER][SENTINEL] 获取 register sentinel"),
        ("获取 create_account sentinel", "[BROWSER][SENTINEL] 获取 create_account sentinel"),
        ("提交邮箱", "[HTTP][EMAIL] 提交邮箱"),
        ("设置密码", "[HTTP][PASSWORD] 设置密码"),
        ("发送验证码", "[HTTP][OTP] 发送验证码"),
        ("验证 OTP", "[HTTP][OTP] 验证 OTP"),
        ("创建账户", "[HTTP][ACCOUNT] 创建账户"),
        ("注册成功", "[DONE][REGISTER] 注册成功"),
        ("请求 codex-auth-url", "[CPA][AUTH] 请求 codex-auth-url"),
        ("转发 callback", "[CPA][CALLBACK] 转发 callback"),
        ("转发响应", "[CPA][CALLBACK] 转发响应"),
        ("等待 token 交换", "[CPA][TOKEN] 等待 token 交换"),
        ("加载授权页", "[BROWSER][NAV] 加载授权页"),
        ("页面:", "[BROWSER][PAGE] 页面:"),
        ("输入邮箱", "[BROWSER][LOGIN] 输入邮箱"),
        ("输入密码", "[BROWSER][LOGIN] 输入密码"),
        ("获取验证码", "[BROWSER][OTP] 获取验证码"),
        ("填入验证码", "[BROWSER][OTP] 填入验证码"),
        ("验证码已提交，等待跳转", "[BROWSER][OTP] 验证码已提交，等待跳转"),
        ("点击 consent", "[BROWSER][CONSENT] 点击 consent"),
        ("需要绑定手机，跳过", "[BROWSER][PHONE] 需要绑定手机，跳过"),
        ("错误页面", "[BROWSER][ERROR] 错误页面"),
        ("截图:", "[BROWSER][SHOT] 截图:"),
        ("失败:", "[ERR] 失败:"),
        ("超时", "[ERR] 超时"),
        ("异常:", "[ERR] 异常:"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)

    if text.startswith("[MainThread]"):
        text = text.replace("[MainThread]", "[TASK]", 1)
    elif text.startswith("[1/") or text.startswith("[*]") or text.startswith("==="):
        text = f"[TASK] {text}"
    elif text.startswith("["):
        text = f"{prefix} {text}"
    else:
        text = f"{prefix} {text}"
    return text


def _stream_process_output(
    proc: subprocess.Popen, log_fn: Callable[[str], None] | None, prefix: str
) -> str:
    output_lines: list[str] = []
    assert proc.stdout is not None
    for raw_line in proc.stdout:
        line = raw_line.rstrip("\r\n")
        output_lines.append(line)
        if log_fn and line:
            formatted = _format_structured_log(prefix, line)
            if formatted:
                log_fn(formatted)
    return "\n".join(output_lines)


def _prewarm_openai_proxy(proxy: str | None) -> None:
    if not proxy:
        return
    proxies = {"http": proxy, "https": proxy}
    last_exc = None
    for _ in range(2):
        try:
            s = cffi_requests.Session(proxies=proxies, impersonate="chrome")
            s.get("https://chatgpt.com", timeout=30)
            s.get("https://chatgpt.com/api/auth/csrf", timeout=20)
            return
        except Exception as exc:
            last_exc = exc
    if last_exc:
        raise last_exc


def probe_openai_proxy(proxy: str | None) -> dict:
    if not proxy:
        return {"ok": True, "steps": ["no-proxy"]}
    proxies = {"http": proxy, "https": proxy}
    steps = []
    try:
        s = cffi_requests.Session(proxies=proxies, impersonate="chrome")
        r1 = s.get("https://chatgpt.com", timeout=30)
        steps.append(f"chatgpt={r1.status_code}")
        r2 = s.get("https://chatgpt.com/api/auth/csrf", timeout=20)
        steps.append(f"csrf={r2.status_code}")
        return {"ok": True, "steps": steps}
    except Exception as exc:
        steps.append(f"error={exc}")
        return {"ok": False, "steps": steps}


def run_original_codex_oauth_bind(
    *,
    email: str,
    password: str,
    cpa_url: str,
    cpa_key: str,
    proxy: str | None,
    headless: bool,
    mail_api_config: dict,
    hotmail_account_record: dict | None = None,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    if not OAUTH_SCRIPT.exists():
        raise RuntimeError(f"未找到原脚本: {OAUTH_SCRIPT}")

    with tempfile.TemporaryDirectory(prefix="codex_bind_") as temp_dir:
        temp_path = Path(temp_dir)
        accounts_file = temp_path / "accounts.txt"
        mail_api_file = temp_path / "mail_api.json"
        accounts_file.write_text(f"{email}----{password}\n", encoding="utf-8")

        runtime_mail_api = dict(mail_api_config or {})
        runtime_mail_api.setdefault("base_dir", str(SCRIPT_DIR))
        if hotmail_account_record:
            hotmail_accounts_file = temp_path / "hotmail_accounts.txt"
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
            runtime_mail_api["accounts_file"] = str(hotmail_accounts_file)
        mail_api_file.write_text(
            json.dumps(runtime_mail_api, ensure_ascii=False, indent=2),
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

        proc = subprocess.Popen(
            command,
            cwd=str(SCRIPT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            shell=False,
            env=_python_subprocess_env(),
        )
        output_text = _stream_process_output(proc, log_fn, "[BIND]")
        try:
            proc.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise

        updated_accounts = accounts_file.read_text(encoding="utf-8", errors="ignore")
        ok = "----done" in updated_accounts and "----fail" not in updated_accounts
        return {
            "ok": ok and proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": output_text,
            "stderr": "",
            "accounts_result": updated_accounts,
            "command": command,
        }


def run_original_codex_register(
    *,
    config_path: str,
    hotmail_account_record: dict | None,
    proxy: str | None,
    headless: bool,
    log_fn: Callable[[str], None] | None = None,
) -> dict:
    if not REGISTER_SCRIPT.exists():
        raise RuntimeError(f"未找到原注册脚本: {REGISTER_SCRIPT}")
    prewarm = probe_openai_proxy(proxy)
    if not prewarm.get("ok"):
        raise RuntimeError(
            "proxy_prewarm_failed: " + " | ".join(prewarm.get("steps") or [])
        )
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
        proc = subprocess.Popen(
            command,
            cwd=str(SCRIPT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            shell=False,
            env=_python_subprocess_env(),
        )
        output_text = _stream_process_output(proc, log_fn, "[REGISTER]")
        try:
            proc.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise
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
        "prewarm": prewarm,
        "returncode": proc.returncode,
        "stdout": output_text,
        "stderr": "",
        "last_registered_line": last_line,
        "command": command,
    }
