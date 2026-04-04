#!/usr/bin/env python3
"""清除 CLIProxyAPI 服务器上失效的认证文件。

删除条件（满足任一）：
  1. unavailable=true（已确认不可用，如 401）
  2. status=error
  3. 无 id_token（OAuth 文件缺少 refresh_token，size ~2KB vs 正常 ~4KB）

边检测边删除，高并发。
"""

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SESSION = requests.Session()
adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)
SESSION.timeout = 15

stats_lock = threading.Lock()
stats = {"found": 0, "deleted": 0, "del_fail": 0}


def get_auth_files(base_url: str, key: str) -> list:
    resp = SESSION.get(
        f"{base_url}/v0/management/auth-files",
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json().get("files", [])


def delete_one(base_url: str, key: str, name: str):
    for attempt in range(3):
        try:
            resp = SESSION.delete(
                f"{base_url}/v0/management/auth-files",
                params={"name": name},
                headers={"Authorization": f"Bearer {key}"},
            )
            resp.raise_for_status()
            with stats_lock:
                stats["deleted"] += 1
            return
        except Exception:
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    with stats_lock:
        stats["del_fail"] += 1


def classify_invalid(files: list, include_disabled: bool) -> list:
    """从列表数据直接判断失效文件，无需逐个请求详情。

    仅处理 provider=codex 的文件，不动其他 OAuth（gemini 等）。
    返回 [(file_dict, reason), ...]
    """
    invalid = []
    for f in files:
        if f.get("runtime_only", False):
            continue

        # 只处理 codex，不碰其他 provider
        if f.get("provider") != "codex":
            continue

        name = f.get("name", "")
        reason = None

        # 1. unavailable
        if f.get("unavailable", False) is True:
            reason = "unavailable"

        # 2. status=error
        elif f.get("status") == "error":
            reason = "error"

        # 3. disabled（可选）
        elif include_disabled and f.get("disabled", False):
            reason = "disabled"

        # 4. OAuth 文件没有 id_token = 缺少 refresh_token
        #    正常完整的 OAuth 文件有 id_token 且 size ~4KB
        #    缺少 refresh_token 的只有 ~2KB 且无 id_token
        elif f.get("account_type") == "oauth" and "id_token" not in f:
            reason = "no_refresh_token"

        if reason:
            invalid.append((f, reason))

    return invalid


def main():
    parser = argparse.ArgumentParser(description="清除 CLIProxyAPI 失效认证文件")
    parser.add_argument("--url", default="https://api.39.la", help="CLIProxyAPI 地址")
    parser.add_argument("--key", required=True, help="管理密钥 (明文)")
    parser.add_argument("--dry-run", action="store_true", help="仅列出，不删除")
    parser.add_argument("--include-disabled", action="store_true", help="也清除被手动禁用的文件")
    parser.add_argument("--workers", type=int, default=50, help="删除并发数 (默认: 50)")
    args = parser.parse_args()

    print("获取认证文件列表...")
    files = get_auth_files(args.url, args.key)
    codex_count = sum(1 for f in files if f.get("provider") == "codex")
    print(f"共 {len(files)} 个认证文件，其中 codex: {codex_count}（仅处理 codex）")

    invalid = classify_invalid(files, args.include_disabled)

    # 统计
    reasons = {}
    for _, reason in invalid:
        reasons[reason] = reasons.get(reason, 0) + 1

    print(f"\n需删除 {len(invalid)} 个：")
    for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    if not invalid:
        print("无需清理。")
        return

    if args.dry_run:
        print(f"\n[dry-run] 前 20 个：")
        for f, reason in invalid[:20]:
            print(f"  {f['name']}  status={f.get('status')}  reason={reason}")
        if len(invalid) > 20:
            print(f"  ... 还有 {len(invalid) - 20} 个")
        return

    print(f"\n开始删除，{args.workers} 线程并发...")
    total = len(invalid)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(delete_one, args.url, args.key, f["name"]) for f, _ in invalid]
        for i, future in enumerate(as_completed(futures), 1):
            if i % 200 == 0 or i == total:
                with stats_lock:
                    d, df = stats["deleted"], stats["del_fail"]
                print(f"\r  进度: {i}/{total}  成功: {d}  失败: {df}", end="", flush=True)

    with stats_lock:
        d, df = stats["deleted"], stats["del_fail"]
    print(f"\n\n完成：删除成功 {d}，失败 {df}，共 {total} 个。")


if __name__ == "__main__":
    main()
