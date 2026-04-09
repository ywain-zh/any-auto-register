import os
from datetime import datetime, timezone
import json
import secrets
import threading
from copy import deepcopy
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from core.base_mailbox import MailboxAccount, create_mailbox
from core.db import MailboxServiceModel, HotmailAccountModel, get_session
from services.hotmail_accounts import (
    HOTMAIL_MAILBOX_STATUS_VALID,
    classify_hotmail_mailbox_error,
    fetch_hotmail_latest_mail,
    get_hotmail_service_config,
    import_hotmail_accounts,
    list_hotmail_accounts,
    list_hotmail_mails,
    refresh_hotmail_token,
    set_hotmail_mailbox_status,
    update_hotmail_registration_status,
)


router = APIRouter(prefix="/mailboxes", tags=["mailboxes"])
ROOT_DIR = Path(__file__).resolve().parent.parent

MAILBOX_PROVIDER_OPTIONS = [
    {"label": "balanced", "value": "balanced"},
    {"label": "prefer_owned", "value": "prefer_owned"},
    {"label": "prefer_public", "value": "prefer_public"},
]

MAILBOX_PROVIDER_DEFINITIONS = [
    {
        "key": "hotmail",
        "label": "Hotmail（导入账号池）",
        "description": "通过导入的 Microsoft/Hotmail 账号池收信。",
        "fields": [
            {
                "key": "hotmail_api_url",
                "label": "Hotmail API URL",
                "type": "textarea",
                "placeholder": "https://www.appleemail.top",
            }
        ],
    },
    {
        "key": "luckmail",
        "label": "LuckMail（订单接码 / 已购邮箱）",
        "description": "对接 LuckMail 平台获取邮箱。",
        "fields": [
            {"key": "luckmail_base_url", "label": "API URL", "placeholder": "https://mails.luckyous.com/"},
            {"key": "luckmail_api_key", "label": "API Key", "secret": True},
            {"key": "luckmail_project_code", "label": "项目代码", "placeholder": "chatgpt / openai"},
            {"key": "luckmail_email_type", "label": "邮箱类型", "placeholder": "outlook"},
            {"key": "luckmail_domain", "label": "邮箱域名", "placeholder": "outlook.com"},
        ],
    },
    {
        "key": "laoudo",
        "label": "Laoudo（固定邮箱）",
        "description": "使用 Laoudo 固定邮箱配置。",
        "fields": [
            {"key": "laoudo_auth", "label": "授权 Token", "secret": True},
            {"key": "laoudo_email", "label": "邮箱地址", "placeholder": "demo@example.com"},
            {"key": "laoudo_account_id", "label": "账号 ID", "placeholder": "123456"},
        ],
    },
    {
        "key": "tempmail_lol",
        "label": "TempMail.lol（自动生成）",
        "description": "自动生成邮箱，无需额外配置。",
        "fields": [],
    },
    {
        "key": "cloudmail",
        "label": "Cloud Mail（自建平台）",
        "description": "对接自建 Cloud Mail 平台。",
        "fields": [
            {"key": "cloudmail_api_url", "label": "API URL", "placeholder": "https://cloudmail.example.com"},
            {"key": "cloudmail_admin_email", "label": "管理员邮箱", "placeholder": "admin@example.com"},
            {"key": "cloudmail_admin_password", "label": "管理员密码", "secret": True},
            {
                "key": "cloudmail_domains",
                "label": "可用域名",
                "type": "textarea",
                "placeholder": "mail.example.com\nmx.example.com",
            },
        ],
    },
    {
        "key": "skymail",
        "label": "SkyMail（CloudMail 接口）",
        "description": "使用 SkyMail / CloudMail 兼容接口。",
        "fields": [
            {"key": "skymail_api_base", "label": "API Base", "placeholder": "https://api.skymail.ink"},
            {"key": "skymail_token", "label": "Token", "secret": True},
            {"key": "skymail_domain", "label": "邮箱域名", "placeholder": "example.com"},
        ],
    },
    {
        "key": "duckmail",
        "label": "DuckMail（自动生成）",
        "description": "对接 DuckMail 平台。",
        "fields": [
            {"key": "duckmail_api_url", "label": "站点 URL", "placeholder": "https://www.duckmail.sbs"},
            {
                "key": "duckmail_provider_url",
                "label": "Provider URL",
                "placeholder": "https://api.duckmail.sbs",
            },
            {"key": "duckmail_bearer", "label": "Bearer", "secret": True},
            {"key": "duckmail_domain", "label": "邮箱域名", "placeholder": "example.com"},
            {"key": "duckmail_api_key", "label": "API Key", "secret": True},
        ],
    },
    {
        "key": "moemail",
        "label": "MoeMail (sall.cc)",
        "description": "使用 MoeMail / sall.cc。",
        "fields": [
            {"key": "moemail_api_url", "label": "API URL", "placeholder": "https://sall.cc"},
        ],
    },
    {
        "key": "maliapi",
        "label": "YYDS Mail / MaliAPI",
        "description": "对接 MaliAPI 获取邮箱。",
        "fields": [
            {"key": "maliapi_base_url", "label": "API URL", "placeholder": "https://maliapi.215.im/v1"},
            {"key": "maliapi_api_key", "label": "API Key", "secret": True},
            {"key": "maliapi_domain", "label": "邮箱域名", "placeholder": "example.com"},
            {
                "key": "maliapi_auto_domain_strategy",
                "label": "自动域名策略",
                "type": "select",
                "options": MAILBOX_PROVIDER_OPTIONS,
            },
        ],
    },
    {
        "key": "gptmail",
        "label": "GPTMail",
        "description": "对接 GPTMail 平台。",
        "fields": [
            {"key": "gptmail_base_url", "label": "API URL", "placeholder": "https://mail.chatgpt.org.uk"},
            {"key": "gptmail_api_key", "label": "API Key", "secret": True},
            {"key": "gptmail_domain", "label": "邮箱域名", "placeholder": "example.com"},
        ],
    },
    {
        "key": "gmail_alias",
        "label": "谷歌别名邮箱",
        "description": "使用 Gmail 原始邮箱 + App Password 生成别名并通过 IMAP 收信。",
        "fields": [
            {
                "key": "gmail_alias_base_email",
                "label": "原始 Gmail 邮箱",
                "placeholder": "zys6626@gmail.com",
                "required": True,
            },
            {
                "key": "gmail_alias_app_password",
                "label": "Gmail 授权密码",
                "secret": True,
                "required": True,
            },
        ],
    },
    {
        "key": "freemail",
        "label": "Freemail（自建 CF Worker）",
        "description": "对接 Freemail 服务。",
        "fields": [
            {"key": "freemail_api_url", "label": "API URL", "placeholder": "https://freemail.example.com"},
            {"key": "freemail_admin_token", "label": "管理员 Token", "secret": True},
            {"key": "freemail_username", "label": "用户名", "placeholder": "admin"},
            {"key": "freemail_password", "label": "密码", "secret": True},
        ],
    },
    {
        "key": "cfworker",
        "label": "CF Worker（自建域名）",
        "description": "基于 Cloudflare Worker 的自建临时邮箱服务。",
        "fields": [
            {"key": "cfworker_api_url", "label": "API URL", "placeholder": "https://apimail.example.com"},
            {"key": "cfworker_admin_token", "label": "管理员 Token", "secret": True},
            {"key": "cfworker_custom_auth", "label": "站点密码", "secret": True},
            {"key": "cfworker_domain", "label": "单域名", "placeholder": "mail.example.com"},
            {
                "key": "cfworker_domain_override",
                "label": "域名覆盖",
                "placeholder": "mail.example.com",
            },
            {"key": "cfworker_subdomain", "label": "固定子域名", "placeholder": "mail / pool-a"},
            {"key": "cfworker_random_subdomain", "label": "随机子域名", "type": "boolean"},
            {"key": "cfworker_fingerprint", "label": "Fingerprint", "placeholder": "6703363b..."},
            {
                "key": "cfworker_domains",
                "label": "全部域名",
                "type": "textarea",
                "placeholder": "mail.example.com\nmx.example.com",
            },
            {
                "key": "cfworker_enabled_domains",
                "label": "启用域名",
                "type": "textarea",
                "placeholder": "mail.example.com\nmx.example.com",
            },
        ],
    },
]
MAILBOX_PROVIDER_MAP = {item["key"]: item for item in MAILBOX_PROVIDER_DEFINITIONS}


def _utcnow():
    return datetime.now(timezone.utc)


_CODEX_BRIDGE_STATE_LOCK = threading.Lock()
_CODEX_BRIDGE_STATE: dict[str, dict] = {}


def _normalize_bridge_token(token: str) -> str:
    value = str(token or "").strip()
    if not value:
        raise HTTPException(400, "bridge token 不能为空")
    return value


def _parse_multiline_domains(raw: str) -> list[str]:
    values = []
    for chunk in str(raw or "").replace("\r", "\n").replace(",", "\n").split("\n"):
        item = chunk.strip().lstrip("@").lower()
        if item:
            values.append(item)
    return list(dict.fromkeys(values))


def _mailbox_content_to_bridge_message(content: str, *, account: MailboxAccount) -> dict:
    text = str(content or "")
    received_at = _utcnow()
    return {
        "subject": "OpenAI / ChatGPT Verification",
        "text": text,
        "body": text,
        "html": text,
        "from": "openai@example.com",
        "to": account.email,
        "posix-millis": int(received_at.timestamp() * 1000),
        "created": received_at.isoformat(),
    }


def _resolve_mailbox_service_record(mailbox_id: int, session: Session) -> MailboxServiceModel:
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item or not item.is_active:
        raise HTTPException(404, "邮箱服务不存在或已停用")
    return item


def _load_codex_bridge_state(token: str) -> dict:
    key = _normalize_bridge_token(token)
    with _CODEX_BRIDGE_STATE_LOCK:
        state = _CODEX_BRIDGE_STATE.get(key)
        if not state:
            raise HTTPException(404, "bridge token 不存在")
        return state


def create_codex_mailbox_bridge(mailbox_service_id: int, config: dict, proxy: str | None = None) -> dict:
    bridge_token = secrets.token_urlsafe(24)
    mailbox = create_mailbox(
        provider=str(config.get("mail_provider") or "").strip(),
        extra=config,
        proxy=proxy,
    )
    account = mailbox.get_email()
    if not account or not account.email:
        raise RuntimeError("邮箱服务未返回可用邮箱")
    state = {
        "mailbox_service_id": mailbox_service_id,
        "mail_provider": str(config.get("mail_provider") or "").strip(),
        "config": deepcopy(config or {}),
        "proxy": proxy or "",
        "mailbox": mailbox,
        "account": account,
        "created_at": _utcnow().isoformat(),
        "lock": threading.Lock(),
        "used_codes": set(),
        "messages": [],
    }
    with _CODEX_BRIDGE_STATE_LOCK:
        _CODEX_BRIDGE_STATE[bridge_token] = state
    return {
        "bridge_token": bridge_token,
        "email": account.email,
    }


def _codex_bridge_base_url() -> str:
    port = str(os.getenv("PORT") or "8000").strip() or "8000"
    host = str(os.getenv("CODEX_BRIDGE_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    return f"http://{host}:{port}/api/mailboxes"


def build_codex_runtime_mail_api(
    *,
    mailbox_service_id: int,
    provider: str,
    merged_extra: dict,
    proxy: str | None = None,
) -> tuple[dict, dict | None]:
    mail_provider = str(provider or "").strip().lower()
    if mail_provider == "hotmail":
        return (
            {
                "provider": "hotmail_api",
                "url": str(merged_extra.get("hotmail_api_url") or "https://www.appleemail.top").strip()
                or "https://www.appleemail.top",
                "base_dir": str(ROOT_DIR / "codex-pool-manager" / "codex-pool-manager"),
            },
            None,
        )
    if mail_provider == "cloudmail":
        runtime_email_domains = _parse_multiline_domains(merged_extra.get("cloudmail_domains") or "")
        return (
            {
                "provider": "cloudmail",
                "url": str(merged_extra.get("cloudmail_api_url") or "").strip(),
                "admin_email": str(merged_extra.get("cloudmail_admin_email") or "").strip(),
                "admin_password": str(merged_extra.get("cloudmail_admin_password") or "").strip(),
                "domains": runtime_email_domains,
                "base_dir": str(ROOT_DIR / "codex-pool-manager" / "codex-pool-manager"),
            },
            None,
        )

    bridge = create_codex_mailbox_bridge(mailbox_service_id, merged_extra, proxy=proxy)
    return (
        {
            "provider": "inbucket",
            "url": f"{_codex_bridge_base_url()}/bridge/{bridge['bridge_token']}",
            "domains": [bridge["email"].split("@", 1)[1]] if "@" in bridge["email"] else [],
            "fixed_email": bridge["email"],
            "base_dir": str(ROOT_DIR / "codex-pool-manager" / "codex-pool-manager"),
        },
        bridge,
    )



def _normalize_mailbox_provider(provider: str) -> str:
    value = str(provider or "").strip().lower()
    if not value:
        raise HTTPException(400, "provider 不能为空")
    if value not in MAILBOX_PROVIDER_MAP:
        raise HTTPException(400, f"不支持的 provider: {value}")
    return value


def _normalize_mailbox_name(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        raise HTTPException(400, "name 不能为空")
    return value


class MailboxServiceCreate(BaseModel):
    name: str
    provider: str
    config: dict


class MailboxServiceUpdate(BaseModel):
    name: str
    provider: str
    config: dict
    is_active: bool = True


class HotmailImportRequest(BaseModel):
    lines: list[str]


class HotmailStatusUpdateRequest(BaseModel):
    email: str
    status: str
    openai_password: str = ""
    error: str = ""
    refresh_token: str = ""


class HotmailBindRequest(BaseModel):
    proxy: str = ""
    headless: bool = False




def _bridge_mailbox_messages(state: dict) -> list[dict]:
    account = state["account"]
    mailbox = state["mailbox"]
    lock = state["lock"]
    with lock:
        try:
            code = mailbox.wait_for_code(
                account,
                keyword="",
                timeout=1,
                before_ids=set(),
                exclude_codes=state["used_codes"],
            )
        except TimeoutError:
            code = ""
        if code:
            state["used_codes"].add(code)
            state["messages"].append(
                _mailbox_content_to_bridge_message(code, account=account)
            )
        return list(state["messages"])


@router.get("/bridge/{bridge_token}/api/v1/mailbox/{local}")
def list_codex_bridge_mailbox(bridge_token: str, local: str):
    state = _load_codex_bridge_state(bridge_token)
    account = state["account"]
    if account.email.split("@", 1)[0].lower() != str(local or "").strip().lower():
        raise HTTPException(404, "邮箱不存在")
    return _bridge_mailbox_messages(state)


@router.get("/bridge/{bridge_token}/api/v1/junkbox/{local}")
def list_codex_bridge_junkbox(bridge_token: str, local: str):
    return list_codex_bridge_mailbox(bridge_token, local)




def _serialize_builtin_mailbox_service(provider: str):
    provider_key = _normalize_mailbox_provider(provider)
    provider_meta = MAILBOX_PROVIDER_MAP[provider_key]
    return {
        "id": f"builtin:{provider_key}",
        "name": provider_meta["label"],
        "provider": provider_key,
        "config": {},
        "is_active": True,
        "created_at": None,
        "updated_at": None,
    }


def _serialize(item: MailboxServiceModel):
    return {
        "id": item.id,
        "name": item.name,
        "provider": item.provider,
        "config": json.loads(item.config_json or "{}"),
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _mask_refresh_token(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if len(token) <= 18:
        return token
    return f"{token[:8]}...{token[-8:]}"


def _serialize_hotmail_account(item):
    return {
        "id": item.id,
        "mailbox_service_id": item.mailbox_service_id,
        "email": item.email,
        "mailbox_password": item.mailbox_password,
        "client_id": item.client_id,
        "refresh_token": item.refresh_token,
        "receive_mode": getattr(item, "receive_mode", "graph") or "graph",
        "mailbox_status": getattr(item, "mailbox_status", "unknown") or "unknown",
        "register_status": item.register_status,
        "claimed_at": item.claimed_at,
        "last_error": item.last_error,
        "openai_password": item.openai_password,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _update_hotmail_account_health(
    *,
    session: Session,
    row: HotmailAccountModel,
    mailbox_status: str,
    last_error: str | None = None,
    refresh_token: str | None = None,
) -> HotmailAccountModel:
    return set_hotmail_mailbox_status(
        session=session,
        row=row,
        mailbox_status=mailbox_status,
        last_error=last_error,
        refresh_token=refresh_token,
    )


def _mark_hotmail_account_status_from_error(
    *,
    session: Session,
    row: HotmailAccountModel,
    error: Exception | str,
) -> str:
    message = str(error or "")
    mailbox_status = classify_hotmail_mailbox_error(message)
    if mailbox_status != (getattr(row, "mailbox_status", "unknown") or "unknown") or message != str(row.last_error or ""):
        _update_hotmail_account_health(
            session=session,
            row=row,
            mailbox_status=mailbox_status,
            last_error=message,
        )
    return message


@router.get("/providers")
def list_mailbox_providers():
    return MAILBOX_PROVIDER_DEFINITIONS


@router.get("")
def list_mailbox_services(session: Session = Depends(get_session)):
    items = session.exec(
        select(MailboxServiceModel).order_by(MailboxServiceModel.updated_at.desc())
    ).all()
    return [_serialize_builtin_mailbox_service("tempmail_lol"), *[_serialize(item) for item in items]]


@router.post("")
def create_mailbox_service(
    body: MailboxServiceCreate, session: Session = Depends(get_session)
):
    provider = _normalize_mailbox_provider(body.provider)
    item = MailboxServiceModel(
        name=_normalize_mailbox_name(body.name),
        provider=provider,
        config_json=json.dumps(body.config or {}, ensure_ascii=False),
        is_active=True,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _serialize(item)


@router.patch("/{mailbox_id}")
def update_mailbox_service(
    mailbox_id: int, body: MailboxServiceUpdate, session: Session = Depends(get_session)
):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item:
        raise HTTPException(404, "邮箱服务不存在")
    provider = _normalize_mailbox_provider(body.provider)
    item.name = _normalize_mailbox_name(body.name)
    item.provider = provider
    item.config_json = json.dumps(body.config or {}, ensure_ascii=False)
    item.is_active = body.is_active
    item.updated_at = _utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return _serialize(item)


@router.delete("/{mailbox_id}")
def delete_mailbox_service(mailbox_id: int, session: Session = Depends(get_session)):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item:
        raise HTTPException(404, "邮箱服务不存在")
    session.delete(item)
    session.commit()
    return {"ok": True}


@router.patch("/{mailbox_id}/toggle")
def toggle_mailbox_service(mailbox_id: int, session: Session = Depends(get_session)):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item:
        raise HTTPException(404, "邮箱服务不存在")
    item.is_active = not item.is_active
    item.updated_at = _utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"is_active": item.is_active}


@router.post("/{mailbox_id}/hotmail/import")
def import_hotmail_accounts_api(
    mailbox_id: int,
    body: HotmailImportRequest,
    session: Session = Depends(get_session),
):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item or item.provider != "hotmail":
        raise HTTPException(404, "Hotmail 邮箱服务不存在")
    return import_hotmail_accounts(
        session=session,
        mailbox_service_id=mailbox_id,
        lines=body.lines,
    )


@router.get("/{mailbox_id}/hotmail/accounts")
def list_hotmail_accounts_api(
    mailbox_id: int,
    page: int = 1,
    page_size: int = 10,
    session: Session = Depends(get_session),
):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item or item.provider != "hotmail":
        raise HTTPException(404, "Hotmail 邮箱服务不存在")
    total, rows = list_hotmail_accounts(
        session=session,
        mailbox_service_id=mailbox_id,
        page=page,
        page_size=page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialize_hotmail_account(row) for row in rows],
    }


@router.get("/{mailbox_id}/hotmail/accounts/{account_id}/latest-mail")
def get_hotmail_latest_mail_api(
    mailbox_id: int,
    account_id: int,
    session: Session = Depends(get_session),
):
    try:
        _, cfg = get_hotmail_service_config(session, mailbox_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    row = session.get(HotmailAccountModel, account_id)
    if not row or row.mailbox_service_id != mailbox_id:
        raise HTTPException(404, "Hotmail 账号不存在")
    try:
        result = fetch_hotmail_latest_mail(
            api_url=cfg.get("hotmail_api_url")
            or cfg.get("api_url")
            or "https://www.appleemail.top",
            email=row.email,
            client_id=row.client_id,
            refresh_token=row.refresh_token,
            receive_mode=getattr(row, "receive_mode", "graph") or "graph",
        )
    except RuntimeError as exc:
        message = _mark_hotmail_account_status_from_error(session=session, row=row, error=exc)
        raise HTTPException(400, message)
    new_refresh_token = str(result.get("new_refresh_token") or "").strip()
    _update_hotmail_account_health(
        session=session,
        row=row,
        mailbox_status=HOTMAIL_MAILBOX_STATUS_VALID,
        last_error="",
        refresh_token=new_refresh_token or None,
    )
    return result


@router.patch("/{mailbox_id}/hotmail/accounts/status")
def update_hotmail_account_status_api(
    mailbox_id: int,
    body: HotmailStatusUpdateRequest,
    session: Session = Depends(get_session),
):
    item = session.get(MailboxServiceModel, mailbox_id)
    if not item or item.provider != "hotmail":
        raise HTTPException(404, "Hotmail 邮箱服务不存在")
    update_hotmail_registration_status(
        session=session,
        mailbox_service_id=mailbox_id,
        email=body.email,
        status=body.status,
        openai_password=body.openai_password,
        error=body.error,
        refresh_token=body.refresh_token,
    )
    return {"ok": True}


@router.get("/{mailbox_id}/hotmail/accounts/{account_id}/mails")
def list_hotmail_account_mails_api(
    mailbox_id: int,
    account_id: int,
    session: Session = Depends(get_session),
):
    try:
        _, cfg = get_hotmail_service_config(session, mailbox_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    row = session.get(HotmailAccountModel, account_id)
    if not row or row.mailbox_service_id != mailbox_id:
        raise HTTPException(404, "Hotmail 账号不存在")
    try:
        result = list_hotmail_mails(
            api_url=cfg.get("hotmail_api_url")
            or cfg.get("api_url")
            or "https://www.appleemail.top",
            email=row.email,
            client_id=row.client_id,
            refresh_token=row.refresh_token,
            receive_mode=getattr(row, "receive_mode", "graph") or "graph",
        )
    except RuntimeError as exc:
        message = _mark_hotmail_account_status_from_error(session=session, row=row, error=exc)
        raise HTTPException(400, message)
    new_refresh_token = str(result.get("new_refresh_token") or "").strip()
    _update_hotmail_account_health(
        session=session,
        row=row,
        mailbox_status=HOTMAIL_MAILBOX_STATUS_VALID,
        last_error="",
        refresh_token=new_refresh_token or None,
    )
    return {"items": result.get("items") or []}


@router.delete("/{mailbox_id}/hotmail/accounts/{account_id}")
def delete_hotmail_account_api(
    mailbox_id: int,
    account_id: int,
    session: Session = Depends(get_session),
):
    try:
        get_hotmail_service_config(session, mailbox_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    row = session.get(HotmailAccountModel, account_id)
    if not row or row.mailbox_service_id != mailbox_id:
        raise HTTPException(404, "Hotmail 账号不存在")
    session.delete(row)
    session.commit()
    return {"ok": True}


@router.post("/{mailbox_id}/hotmail/accounts/{account_id}/refresh-token")
def refresh_hotmail_account_token_api(
    mailbox_id: int,
    account_id: int,
    session: Session = Depends(get_session),
):
    try:
        get_hotmail_service_config(session, mailbox_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    row = session.get(HotmailAccountModel, account_id)
    if not row or row.mailbox_service_id != mailbox_id:
        raise HTTPException(404, "Hotmail 账号不存在")
    try:
        result = refresh_hotmail_token(
            client_id=row.client_id,
            refresh_token=row.refresh_token,
            receive_mode=getattr(row, "receive_mode", "graph") or "graph",
        )
    except RuntimeError as exc:
        message = _mark_hotmail_account_status_from_error(session=session, row=row, error=exc)
        raise HTTPException(400, message)
    latest_refresh_token = str(result.get("refresh_token") or "").strip()
    refresh_token_updated = bool(
        latest_refresh_token and latest_refresh_token != str(row.refresh_token or "").strip()
    )
    row = _update_hotmail_account_health(
        session=session,
        row=row,
        mailbox_status=HOTMAIL_MAILBOX_STATUS_VALID,
        last_error="",
        refresh_token=latest_refresh_token or None,
    )
    return {
        "ok": True,
        "receive_mode": result.get("receive_mode") or "graph",
        "token_url": result.get("token_url") or "",
        "scope": result.get("scope") or "",
        "refresh_token_updated": refresh_token_updated,
        "refresh_token_preview": _mask_refresh_token(latest_refresh_token or row.refresh_token),
    }


@router.post("/{mailbox_id}/hotmail/accounts/{account_id}/bind")
def bind_hotmail_account_api(
    mailbox_id: int,
    account_id: int,
    body: HotmailBindRequest,
    session: Session = Depends(get_session),
):
    try:
        _, cfg = get_hotmail_service_config(session, mailbox_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    row = session.get(HotmailAccountModel, account_id)
    if not row or row.mailbox_service_id != mailbox_id:
        raise HTTPException(404, "Hotmail 账号不存在")
    if not row.openai_password:
        raise HTTPException(400, "该账号还没有 OpenAI 密码，无法直接登录绑定")
    if row.register_status == "unregistered":
        raise HTTPException(400, "未注册账号不能直接登录绑定，请先走完整注册流程")

    from core.config_store import config_store
    from services.codex_script_bridge import resolve_codex_bind_target, run_codex_oauth_bind

    all_cfg = config_store.get_all()
    bind_target = resolve_codex_bind_target(all_cfg)
    cpa_url = (
        all_cfg.get("cliproxyapi_base_url", "")
        or all_cfg.get("cpa_api_url", "")
        or all_cfg.get("codex_proxy_url", "")
    )
    cpa_key = (
        all_cfg.get("cliproxyapi_management_key", "")
        or all_cfg.get("cpa_api_key", "")
        or all_cfg.get("codex_proxy_key", "")
    )
    sub2api_url = all_cfg.get("sub2api_api_url", "")
    sub2api_key = all_cfg.get("sub2api_api_key", "")
    if bind_target == "sub2api":
        if not sub2api_url or not sub2api_key:
            raise HTTPException(400, "未配置 Sub2API 地址或 API Key")
    elif not cpa_url or not cpa_key:
        raise HTTPException(400, "未配置 CLIProxyAPI / CPA 地址或管理口令")

    try:
        result = run_codex_oauth_bind(
            bind_target=bind_target,
            email=row.email,
            password=row.openai_password,
            proxy=body.proxy or None,
            headless=body.headless,
            cpa_url=str(cpa_url).strip(),
            cpa_key=str(cpa_key).strip(),
            sub2api_url=str(sub2api_url).strip(),
            sub2api_key=str(sub2api_key).strip(),
            mail_api_config={
                "provider": "hotmail_api",
                "url": cfg.get("hotmail_api_url")
                or cfg.get("api_url")
                or "https://www.appleemail.top",
                "base_dir": str(ROOT_DIR / "codex-pool-manager" / "codex-pool-manager"),
            },
            hotmail_account_record={
                "email": row.email,
                "mailbox_password": row.mailbox_password,
                "client_id": row.client_id,
                "refresh_token": row.refresh_token,
            },
        )
        if not result.get("ok"):
            raise RuntimeError(
                result.get("stderr")
                or result.get("stdout")
                or result.get("message")
                or "原脚本执行失败"
            )
        update_hotmail_registration_status(
            session=session,
            mailbox_service_id=mailbox_id,
            email=row.email,
            status="success",
            openai_password=row.openai_password,
        )
        return {"ok": True, "result": result}
    except Exception as exc:
        update_hotmail_registration_status(
            session=session,
            mailbox_service_id=mailbox_id,
            email=row.email,
            status="failed",
            error=str(exc),
        )
        raise HTTPException(400, str(exc))
