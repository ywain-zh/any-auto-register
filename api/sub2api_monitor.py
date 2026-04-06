from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.sub2api_monitor import latest_report, resolve_sub2api_config, run_sub2api_monitor


router = APIRouter(prefix="/sub2api-monitor", tags=["sub2api-monitor"])


class Sub2ApiMonitorRunRequest(BaseModel):
    page_size: int = 100
    max_pages: int = 20
    enable_remote_test: bool = True
    stop_on_error: bool = False


@router.get("/status")
def sub2api_monitor_status():
    base_url, api_key = resolve_sub2api_config()
    return {
        "configured": bool(base_url and api_key),
        "base_url": base_url,
        "has_api_key": bool(api_key),
        "latest_report": latest_report(),
    }


@router.post("/run")
def sub2api_monitor_run(body: Sub2ApiMonitorRunRequest):
    base_url, api_key = resolve_sub2api_config()
    if not base_url or not api_key:
        raise HTTPException(400, "未配置 Sub2API API 地址或 API Key")

    try:
        result = run_sub2api_monitor(
            page_size=body.page_size,
            max_pages=body.max_pages,
            enable_remote_test=body.enable_remote_test,
            stop_on_error=body.stop_on_error,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Sub2API 监控执行失败: {exc}") from exc

    return {
        **result,
        "latest_report": latest_report(),
    }
