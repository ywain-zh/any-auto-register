#!/usr/bin/env python3
"""
Sentinel Token 浏览器获取模块
==============================
打开 sentinel frame 页面，调用 SentinelSDK.token() 获取完整 token (p+t+c)。
参考: https://sentinel.openai.com/backend-api/sentinel/frame.html
"""

import json
import os
import time

SDK_URL = "https://sentinel.openai.com/sentinel/20260219f9f6/sdk.js"
FRAME_URL = "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def get_sentinel_tokens(flows=None, proxy=None, headless=True, timeout=60):
    """
    获取多个 flow 的 sentinel token。

    参数:
      flows: flow 名称列表，如 ["username_password_create", "oauth_create_account"]
      proxy: 代理地址
      headless: 无头模式
      timeout: 超时秒数

    返回:
      {flow_name: {"p": ..., "t": ..., "c": ..., "id": ..., "flow": ...}, ...}
      或 None
    """
    if not flows:
        flows = ["username_password_create"]

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        launch_kw = {"headless": headless}
        if proxy:
            launch_kw["proxy"] = {"server": proxy}

        browser = p.chromium.launch(**launch_kw)
        context = browser.new_context(
            user_agent=UA,
            locale="en-US",
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        try:
            page.goto(FRAME_URL, wait_until="load", timeout=timeout * 1000)
            page.wait_for_timeout(5000)
            page.wait_for_function("() => !!window.SentinelSDK", timeout=30000)

            result = page.evaluate(
                """async (flows) => {
                    const out = {};
                    if (!window.SentinelSDK) throw new Error('SentinelSDK missing');
                    for (const flow of flows) {
                        try {
                            await window.SentinelSDK.init(flow);
                            const tok = await window.SentinelSDK.token(flow);
                            out[flow] = tok ? JSON.parse(tok) : null;
                        } catch (e) {
                            out[flow] = null;
                        }
                    }
                    return out;
                }""",
                flows,
            )

            browser.close()
            return result

        except Exception as e:
            print(f"  [Sentinel] 异常: {e}", flush=True)
            browser.close()
            return None


def get_sentinel_token_str(flow="username_password_create", proxy=None, headless=True):
    """
    获取单个 flow 的 sentinel token JSON 字符串。
    可直接用于 openai-sentinel-token header。
    """
    result = get_sentinel_tokens([flow], proxy=proxy, headless=headless)
    if result and result.get(flow):
        return json.dumps(result[flow])
    return None


if __name__ == "__main__":
    print("获取 sentinel tokens...")
    tokens = get_sentinel_tokens(["username_password_create", "oauth_create_account"])
    if tokens:
        for flow, tok in tokens.items():
            if tok:
                p = tok.get("p", "")[:50]
                t = tok.get("t", "")[:50]
                c = tok.get("c", "")[:50]
                print(f"  {flow}: p={p}... t={t}... c={c}...")
            else:
                print(f"  {flow}: FAILED")
    else:
        print("Failed")
