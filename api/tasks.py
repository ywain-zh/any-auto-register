from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from typing import Optional
from copy import deepcopy
import sys
from core.db import TaskLog, MailboxServiceModel, engine
from core.task_runtime import (
    AttemptOutcome,
    AttemptResult,
    RegisterTaskStore,
    SkipCurrentAttemptRequested,
    StopTaskRequested,
)
import time, json, asyncio, threading, logging

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)

MAX_FINISHED_TASKS = 200
CLEANUP_THRESHOLD = 250
_task_store = RegisterTaskStore(
    max_finished_tasks=MAX_FINISHED_TASKS,
    cleanup_threshold=CLEANUP_THRESHOLD,
)


class RegisterTaskRequest(BaseModel):
    platform: str
    email: Optional[str] = None
    password: Optional[str] = None
    count: int = 1
    concurrency: int = 1
    register_delay_seconds: float = 0
    proxy: Optional[str] = None
    executor_type: str = "protocol"
    captcha_solver: str = "yescaptcha"
    extra: dict = Field(default_factory=dict)


class TaskLogBatchDeleteRequest(BaseModel):
    ids: list[int]


def _ensure_task_exists(task_id: str) -> None:
    if not _task_store.exists(task_id):
        raise HTTPException(404, "任务不存在")


def _ensure_task_mutable(task_id: str) -> None:
    _ensure_task_exists(task_id)
    snapshot = _task_store.snapshot(task_id)
    if snapshot.get("status") in {"done", "failed", "stopped"}:
        raise HTTPException(409, "任务已结束，无法再执行控制操作")


def _prepare_register_request(req: RegisterTaskRequest) -> RegisterTaskRequest:
    from core.config_store import config_store

    req_data = req.model_dump()
    req_data["extra"] = deepcopy(req_data.get("extra") or {})
    if not req_data.get("proxy") and req_data["extra"].get("proxy"):
        req_data["proxy"] = req_data["extra"].get("proxy")
    prepared = RegisterTaskRequest(**req_data)

    mailbox_service_id = prepared.extra.get("mailbox_service_id")
    if mailbox_service_id:
        if isinstance(mailbox_service_id, str) and mailbox_service_id.startswith(
            "builtin:"
        ):
            prepared.extra["mail_provider"] = mailbox_service_id.split(":", 1)[1]
        else:
            with Session(engine) as session:
                mailbox_item = session.get(MailboxServiceModel, int(mailbox_service_id))
                if not mailbox_item or not mailbox_item.is_active:
                    raise HTTPException(400, "所选邮箱服务不存在或已停用")
                prepared.extra["mail_provider"] = mailbox_item.provider
                prepared.extra.update(json.loads(mailbox_item.config_json or "{}"))
                prepared.extra["hotmail_mailbox_service_id"] = mailbox_item.id

    mail_provider = prepared.extra.get("mail_provider") or config_store.get(
        "mail_provider", ""
    )
    if mail_provider == "luckmail":
        platform = prepared.platform
        if platform in ("tavily", "openblocklabs"):
            raise HTTPException(400, f"LuckMail 渠道暂时不支持 {platform} 项目注册")

        mapping = {
            "trae": "trae",
            "cursor": "cursor",
            "grok": "grok",
            "kiro": "kiro",
            "chatgpt": "openai",
        }
        prepared.extra["luckmail_project_code"] = mapping.get(platform, platform)

    return prepared


def _mark_hotmail_status(
    extra: dict, email: str, status: str, *, openai_password: str = "", error: str = ""
) -> None:
    mailbox_service_id = int(extra.get("hotmail_mailbox_service_id") or 0)
    if not mailbox_service_id or not email:
        return
    from sqlmodel import Session
    from core.db import engine
    from services.hotmail_accounts import update_hotmail_registration_status

    with Session(engine) as session:
        update_hotmail_registration_status(
            session=session,
            mailbox_service_id=mailbox_service_id,
            email=email,
            status=status,
            openai_password=openai_password,
            error=error,
        )


def _run_codex_via_original_scripts(
    task_id: str, req: RegisterTaskRequest, proxy: str | None
):
    from core.config_store import config_store
    from sqlmodel import Session, select
    from services.codex_script_bridge import (
        ROOT_DIR as BRIDGE_ROOT,
        SCRIPT_DIR,
        run_original_codex_oauth_bind,
        run_original_codex_register,
    )
    from core.db import HotmailAccountModel

    merged_extra = config_store.get_all().copy()
    merged_extra.update(
        {k: v for k, v in req.extra.items() if v is not None and v != ""}
    )
    mail_provider = str(merged_extra.get("mail_provider") or "").strip().lower()
    mailbox_service_id = int(merged_extra.get("hotmail_mailbox_service_id") or 0)
    if mail_provider not in {"hotmail", "cloudmail"}:
        raise RuntimeError("Codex 原脚本桥接当前仅支持 Hotmail / CloudMail 服务实例")

    cpa_url = str(
        merged_extra.get("cliproxyapi_base_url")
        or merged_extra.get("cpa_api_url")
        or merged_extra.get("codex_proxy_url")
        or ""
    ).strip()
    cpa_key = str(
        merged_extra.get("cliproxyapi_management_key")
        or merged_extra.get("cpa_api_key")
        or merged_extra.get("codex_proxy_key")
        or ""
    ).strip()
    if not cpa_url or not cpa_key:
        raise RuntimeError("未配置 CLIProxyAPI / CPA 地址或管理口令")

    row = None
    hotmail_record = None
    if mail_provider == "hotmail":
        with Session(engine) as s:
            row = s.exec(
                select(HotmailAccountModel)
                .where(HotmailAccountModel.mailbox_service_id == mailbox_service_id)
                .where(HotmailAccountModel.register_status == "unregistered")
                .order_by(HotmailAccountModel.created_at.asc())
            ).first()
        if not row:
            raise RuntimeError("没有可用的未注册 Hotmail 账号")
        hotmail_record = {
            "email": row.email,
            "mailbox_password": row.mailbox_password,
            "client_id": row.client_id,
            "refresh_token": row.refresh_token,
        }
        _log(task_id, f"Codex 原脚本桥接将使用邮箱: {row.email}")
    _log(task_id, f"Codex 原脚本桥接收到代理: {proxy}")

    runtime_email_domains = (
        []
        if mail_provider == "hotmail"
        else [
            x.strip()
            for x in str(merged_extra.get("cloudmail_domains") or "").splitlines()
            if x.strip()
        ]
    )
    runtime_mail_api = (
        {
            "provider": "hotmail_api",
            "url": "https://www.appleemail.top",
            "accounts_file": str(SCRIPT_DIR / "hotmail_accounts_runtime.txt"),
            "base_dir": str(SCRIPT_DIR),
        }
        if mail_provider == "hotmail"
        else {
            "provider": "cloudmail",
            "url": str(merged_extra.get("cloudmail_api_url") or "").strip(),
            "admin_email": str(merged_extra.get("cloudmail_admin_email") or "").strip(),
            "admin_password": str(
                merged_extra.get("cloudmail_admin_password") or ""
            ).strip(),
            "domains": runtime_email_domains,
            "base_dir": str(SCRIPT_DIR),
        }
    )
    config_path = SCRIPT_DIR / f"pool_config.{mail_provider}.runtime.yaml"
    config_path.write_text(
        json.dumps(
            {
                "cliproxy": {"url": cpa_url, "key": cpa_key},
                "email_domains": runtime_email_domains,
                "mail_api": runtime_mail_api,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if hotmail_record:
        (SCRIPT_DIR / "hotmail_accounts_runtime.txt").write_text(
            "----".join(
                [
                    str(hotmail_record.get("email") or ""),
                    str(hotmail_record.get("mailbox_password") or ""),
                    str(hotmail_record.get("client_id") or ""),
                    str(hotmail_record.get("refresh_token") or ""),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    is_headless = req.executor_type != "headed"
    _log(
        task_id,
        f"[CODEX] executor_type={req.executor_type}, headless={str(is_headless).lower()}",
    )
    _log(task_id, f"[CODEX] 开始执行注册脚本，provider={mail_provider}")
    reg_result = run_original_codex_register(
        config_path=str(config_path),
        hotmail_account_record=hotmail_record,
        proxy=proxy,
        headless=is_headless,
        log_fn=lambda msg: _log(task_id, msg),
    )
    _log(task_id, f"Codex 注册预热: {reg_result.get('prewarm')}")
    _log(task_id, f"Codex 注册命令: {' '.join(reg_result.get('command') or [])}")
    if not reg_result.get("ok"):
        raise RuntimeError(
            reg_result.get("stderr") or reg_result.get("stdout") or "原注册脚本失败"
        )

    last_line = str(reg_result.get("last_registered_line") or "")
    parts = last_line.split("----")
    if len(parts) < 2:
        raise RuntimeError(f"无法解析原注册结果: {last_line}")
    email, openai_password = parts[0], parts[1]
    _log(task_id, f"[CODEX] 注册阶段成功: {email}")
    _log(task_id, f"[CODEX] 开始执行 OAuth / CPA 绑定，provider={mail_provider}")
    bind_result = None
    if mail_provider == "hotmail":
        _mark_hotmail_status(
            merged_extra,
            email,
            "pending_bind",
            openai_password=openai_password,
        )
    bind_result = run_original_codex_oauth_bind(
        email=email,
        password=openai_password,
        cpa_url=cpa_url,
        cpa_key=cpa_key,
        proxy=proxy,
        headless=is_headless,
        mail_api_config=runtime_mail_api,
        hotmail_account_record=hotmail_record,
        log_fn=lambda msg: _log(task_id, msg),
    )
    if not bind_result.get("ok"):
        raise RuntimeError(
            bind_result.get("stderr")
            or bind_result.get("stdout")
            or "原 OAuth 脚本失败"
        )
    if mail_provider == "hotmail":
        _mark_hotmail_status(
            merged_extra,
            email,
            "success",
            openai_password=openai_password,
        )
    _log(task_id, f"[OK] Codex 原脚本完整流程成功: {email}")
    return {
        "email": email,
        "password": openai_password,
        "detail": {"register": reg_result, "bind": bind_result},
    }


def _create_task_record(
    task_id: str, req: RegisterTaskRequest, source: str, meta: dict | None = None
):
    _task_store.create(
        task_id,
        platform=req.platform,
        total=req.count,
        source=source,
        meta=meta,
    )


def enqueue_register_task(
    req: RegisterTaskRequest,
    *,
    background_tasks: BackgroundTasks | None = None,
    source: str = "manual",
    meta: dict | None = None,
) -> str:
    prepared = _prepare_register_request(req)
    task_id = f"task_{int(time.time() * 1000)}"
    _create_task_record(task_id, prepared, source, meta)
    _log(task_id, f"收到任务代理: {req.proxy}")
    _log(task_id, f"准备后任务代理: {prepared.proxy}")
    if background_tasks is None:
        thread = threading.Thread(
            target=_run_register, args=(task_id, prepared), daemon=True
        )
        thread.start()
    else:
        background_tasks.add_task(_run_register, task_id, prepared)
    return task_id


def has_active_register_task(
    *, platform: str | None = None, source: str | None = None
) -> bool:
    return _task_store.has_active(platform=platform, source=source)


def _log(task_id: str, msg: str):
    """向任务追加一条日志"""
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    _task_store.append_log(task_id, entry)
    try:
        print(entry)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_entry = entry.encode(encoding, errors="replace").decode(
            encoding, errors="replace"
        )
        print(safe_entry)


def _save_task_log(
    platform: str, email: str, status: str, error: str = "", detail: dict = None
):
    """Write a TaskLog record to the database."""
    with Session(engine) as s:
        log = TaskLog(
            platform=platform,
            email=email,
            status=status,
            error=error,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
        s.add(log)
        s.commit()


def _auto_upload_integrations(task_id: str, account):
    """注册成功后自动导入外部系统。"""
    try:
        from services.external_sync import sync_account

        for result in sync_account(account):
            name = result.get("name", "Auto Upload")
            ok = bool(result.get("ok"))
            msg = result.get("msg", "")
            _log(task_id, f"  [{name}] {'[OK] ' + msg if ok else '[ERR] ' + msg}")
    except Exception as e:
        _log(task_id, f"  [Auto Upload] 自动导入异常: {e}")


def _run_register(task_id: str, req: RegisterTaskRequest):
    from core.registry import get
    from core.base_platform import RegisterConfig
    from core.db import save_account
    from core.base_mailbox import create_mailbox
    from core.proxy_utils import normalize_proxy_url

    control = _task_store.control_for(task_id)
    _task_store.mark_running(task_id)
    success = 0
    skipped = 0
    errors = []
    start_gate_lock = threading.Lock()
    next_start_time = time.time()

    def _sleep_with_control(wait_seconds: float) -> None:
        remaining = max(float(wait_seconds or 0), 0.0)
        while remaining > 0:
            control.checkpoint()
            chunk = min(0.25, remaining)
            time.sleep(chunk)
            remaining -= chunk

    try:
        PlatformCls = get(req.platform)

        def _build_mailbox(proxy: Optional[str]):
            from core.config_store import config_store

            merged_extra = config_store.get_all().copy()
            merged_extra.update(
                {k: v for k, v in req.extra.items() if v is not None and v != ""}
            )
            return create_mailbox(
                provider=merged_extra.get("mail_provider", "luckmail"),
                extra=merged_extra,
                proxy=proxy,
            )

        def _do_one(i: int):
            nonlocal next_start_time
            proxy_pool = None
            _proxy = None
            current_email = req.email or ""
            try:
                from core.proxy_pool import proxy_pool

                control.checkpoint()
                _proxy = req.proxy
                if not _proxy:
                    _proxy = proxy_pool.get_next()
                _proxy = normalize_proxy_url(_proxy)
                if req.register_delay_seconds > 0:
                    with start_gate_lock:
                        control.checkpoint()
                        now = time.time()
                        wait_seconds = max(0.0, next_start_time - now)
                        if wait_seconds > 0:
                            _log(
                                task_id,
                                f"第 {i + 1} 个账号启动前延迟 {wait_seconds:g} 秒",
                            )
                            _sleep_with_control(wait_seconds)
                        next_start_time = time.time() + req.register_delay_seconds
                control.checkpoint()
                from core.config_store import config_store

                merged_extra = config_store.get_all().copy()
                merged_extra.update(
                    {k: v for k, v in req.extra.items() if v is not None and v != ""}
                )

                _config = RegisterConfig(
                    executor_type=req.executor_type,
                    captcha_solver=req.captcha_solver,
                    proxy=_proxy,
                    extra=merged_extra,
                )
                _mailbox = _build_mailbox(_proxy)
                _platform = PlatformCls(config=_config, mailbox=_mailbox)
                _platform._log_fn = lambda msg: _log(task_id, msg)
                _platform.bind_task_control(control)
                if getattr(_platform, "mailbox", None) is not None:
                    _platform.mailbox._log_fn = _platform._log_fn
                _task_store.set_progress(task_id, f"{i + 1}/{req.count}")
                _log(task_id, f"开始注册第 {i + 1}/{req.count} 个账号")
                if _proxy:
                    _log(task_id, f"使用代理: {_proxy}")
                if req.platform == "codex":
                    result = _run_codex_via_original_scripts(task_id, req, _proxy)
                    current_email = result.get("email") or current_email
                    _save_task_log(
                        req.platform, current_email, "success", detail=result
                    )
                    return AttemptResult.success()
                account = _platform.register(
                    email=req.email or None,
                    password=req.password,
                )
                current_email = account.email or current_email
                if isinstance(account.extra, dict):
                    mail_provider = merged_extra.get("mail_provider", "")
                    if mail_provider:
                        account.extra.setdefault("mail_provider", mail_provider)
                    if mail_provider == "luckmail" and req.platform == "chatgpt":
                        mailbox_token = getattr(_mailbox, "_token", "") or ""
                        if mailbox_token:
                            account.extra.setdefault("mailbox_token", mailbox_token)
                        if merged_extra.get("luckmail_project_code"):
                            account.extra.setdefault(
                                "luckmail_project_code",
                                merged_extra.get("luckmail_project_code"),
                            )
                        if merged_extra.get("luckmail_email_type"):
                            account.extra.setdefault(
                                "luckmail_email_type",
                                merged_extra.get("luckmail_email_type"),
                            )
                        if merged_extra.get("luckmail_domain"):
                            account.extra.setdefault(
                                "luckmail_domain", merged_extra.get("luckmail_domain")
                            )
                        if merged_extra.get("luckmail_base_url"):
                            account.extra.setdefault(
                                "luckmail_base_url",
                                merged_extra.get("luckmail_base_url"),
                            )
                saved_account = save_account(account)
                if (
                    req.platform != "codex"
                    and merged_extra.get("mail_provider") == "hotmail"
                ):
                    _mark_hotmail_status(
                        merged_extra,
                        account.email,
                        "success",
                        openai_password=account.password,
                    )
                if _proxy:
                    proxy_pool.report_success(_proxy)
                _log(task_id, f"[OK] 注册成功: {account.email}")
                _save_task_log(req.platform, account.email, "success")
                _auto_upload_integrations(task_id, saved_account or account)
                cashier_url = (account.extra or {}).get("cashier_url", "")
                if cashier_url:
                    _log(task_id, f"  [升级链接] {cashier_url}")
                    _task_store.add_cashier_url(task_id, cashier_url)
                return AttemptResult.success()
            except SkipCurrentAttemptRequested as e:
                _log(task_id, f"↷ 已跳过当前账号: {e}")
                _save_task_log(
                    req.platform,
                    current_email,
                    "skipped",
                    error=str(e),
                )
                return AttemptResult.skipped(str(e))
            except StopTaskRequested as e:
                _log(task_id, f"■ {e}")
                return AttemptResult.stopped(str(e))
            except Exception as e:
                if _proxy and proxy_pool is not None:
                    proxy_pool.report_fail(_proxy)
                if (
                    req.platform == "codex"
                    and merged_extra.get("mail_provider") == "hotmail"
                ):
                    _mark_hotmail_status(
                        merged_extra,
                        current_email,
                        "failed",
                        error=str(e),
                    )
                _log(task_id, f"[ERR] 注册失败: {e}")
                _save_task_log(
                    req.platform,
                    current_email,
                    "failed",
                    error=str(e),
                )
                return AttemptResult.failed(str(e))

        from concurrent.futures import ThreadPoolExecutor, as_completed

        max_workers = min(req.concurrency, req.count, 5)
        stopped = False
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_do_one, i) for i in range(req.count)]
            for f in as_completed(futures):
                try:
                    result = f.result()
                except Exception as e:
                    _log(task_id, f"[ERR] 任务线程异常: {e}")
                    errors.append(str(e))
                    continue
                if result.outcome == AttemptOutcome.SUCCESS:
                    success += 1
                elif result.outcome == AttemptOutcome.SKIPPED:
                    skipped += 1
                elif result.outcome == AttemptOutcome.STOPPED:
                    stopped = True
                else:
                    errors.append(result.message)
    except Exception as e:
        _log(task_id, f"致命错误: {e}")
        _task_store.finish(
            task_id,
            status="failed",
            success=success,
            skipped=skipped,
            errors=errors,
            error=str(e),
        )
        _task_store.cleanup()
        return

    final_status = "stopped" if control.is_stop_requested() or stopped else "done"
    if final_status == "stopped":
        summary = (
            f"任务已停止: 成功 {success} 个, 跳过 {skipped} 个, 失败 {len(errors)} 个"
        )
    else:
        summary = f"完成: 成功 {success} 个, 跳过 {skipped} 个, 失败 {len(errors)} 个"
    _log(task_id, summary)
    _task_store.finish(
        task_id,
        status=final_status,
        success=success,
        skipped=skipped,
        errors=errors,
    )
    _task_store.cleanup()


@router.post("/register")
def create_register_task(
    req: RegisterTaskRequest,
    background_tasks: BackgroundTasks,
):
    task_id = enqueue_register_task(req, background_tasks=background_tasks)
    return {"task_id": task_id}


@router.post("/{task_id}/skip-current")
def skip_current_account(task_id: str):
    _ensure_task_mutable(task_id)
    control = _task_store.request_skip_current(task_id)
    _log(task_id, "收到手动跳过当前账号请求")
    return {"ok": True, "task_id": task_id, "control": control}


@router.post("/{task_id}/stop")
def stop_task(task_id: str):
    _ensure_task_mutable(task_id)
    control = _task_store.request_stop(task_id)
    _log(task_id, "收到手动停止任务请求")
    return {"ok": True, "task_id": task_id, "control": control}


@router.get("/logs")
def get_logs(platform: str = None, page: int = 1, page_size: int = 50):
    with Session(engine) as s:
        q = select(TaskLog)
        if platform:
            q = q.where(TaskLog.platform == platform)
        q = q.order_by(TaskLog.id.desc())
        total = len(s.exec(q).all())
        items = s.exec(q.offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "items": items}


@router.post("/logs/batch-delete")
def batch_delete_logs(body: TaskLogBatchDeleteRequest):
    if not body.ids:
        raise HTTPException(400, "任务历史 ID 列表不能为空")

    unique_ids = list(dict.fromkeys(body.ids))
    if len(unique_ids) > 1000:
        raise HTTPException(400, "单次最多删除 1000 条任务历史")

    with Session(engine) as s:
        try:
            logs = s.exec(select(TaskLog).where(TaskLog.id.in_(unique_ids))).all()
            found_ids = {log.id for log in logs if log.id is not None}

            for log in logs:
                s.delete(log)

            s.commit()
            deleted_count = len(found_ids)
            not_found_ids = [log_id for log_id in unique_ids if log_id not in found_ids]
            logger.info("批量删除任务历史成功: %s 条", deleted_count)

            return {
                "deleted": deleted_count,
                "not_found": not_found_ids,
                "total_requested": len(unique_ids),
            }
        except Exception as e:
            s.rollback()
            logger.exception("批量删除任务历史失败")
            raise HTTPException(500, f"批量删除任务历史失败: {str(e)}")


@router.get("/{task_id}/logs/stream")
async def stream_logs(task_id: str, since: int = 0):
    """SSE 实时日志流"""
    _ensure_task_exists(task_id)

    async def event_generator():
        sent = since
        while True:
            logs, status = _task_store.log_state(task_id)
            while sent < len(logs):
                yield f"data: {json.dumps({'line': logs[sent]})}\n\n"
                sent += 1
            if status in ("done", "failed", "stopped"):
                yield f"data: {json.dumps({'done': True, 'status': status})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{task_id}")
def get_task(task_id: str):
    _ensure_task_exists(task_id)
    return _task_store.snapshot(task_id)


@router.get("")
def list_tasks():
    return _task_store.list_snapshots()
