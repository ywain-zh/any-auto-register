from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.config_store import config_store


router = APIRouter(prefix="/cpa-monitor", tags=["cpa-monitor"])


ROOT_DIR = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = ROOT_DIR / "check.js"
REPORT_DIR = ROOT_DIR / "reports" / "cliproxyapi-auth-cleaner"


class CpaMonitorRunRequest(BaseModel):
    dry_run: bool = False
    once: bool = True
    enable_api_call_check: bool = False
    enable_disabled_recovery: bool = True


def _resolve_cpa_config() -> tuple[str, str]:
    base_url = (
        config_store.get("cliproxyapi_base_url", "")
        or config_store.get("cpa_api_url", "")
        or config_store.get("codex_proxy_url", "")
    )
    key = (
        config_store.get("cliproxyapi_management_key", "")
        or config_store.get("cpa_api_key", "")
        or config_store.get("codex_proxy_key", "")
    )
    return str(base_url or "").strip(), str(key or "").strip()


def _latest_report() -> dict | None:
    if not REPORT_DIR.exists():
        return None
    reports = sorted(
        REPORT_DIR.glob("report-*.json"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not reports:
        return None
    path = reports[0]
    try:
        return {
            "path": str(path.relative_to(ROOT_DIR)),
            "content": json.loads(path.read_text(encoding="utf-8")),
        }
    except Exception:
        return {
            "path": str(path.relative_to(ROOT_DIR)),
            "content": None,
        }


@router.get("/status")
def cpa_monitor_status():
    base_url, key = _resolve_cpa_config()
    return {
        "configured": bool(base_url and key),
        "base_url": base_url,
        "has_management_key": bool(key),
        "latest_report": _latest_report(),
    }


@router.post("/run")
def run_cpa_monitor(body: CpaMonitorRunRequest):
    if not CHECK_SCRIPT.exists():
        raise HTTPException(404, "未找到 check.js")

    base_url, key = _resolve_cpa_config()
    if not base_url or not key:
        raise HTTPException(400, "未配置 CLIProxyAPI / CPA 地址或管理口令")

    command = [
        "node",
        str(CHECK_SCRIPT),
        "--base-url",
        base_url,
        "--management-key",
        key,
    ]
    if body.once:
        command.append("--once")
    if body.dry_run:
        command.append("--dry-run")
    if body.enable_api_call_check:
        command.append("--enable-api-call-check")
    if body.enable_disabled_recovery:
        command.append("--enable-disabled-recovery")

    proc = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        timeout=600,
        encoding="utf-8",
        errors="ignore",
        shell=False,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "command": command,
        "latest_report": _latest_report(),
    }
