#!/bin/bash
warp-svc &
sleep 3

if ! warp-cli --accept-tos status 2>/dev/null | grep -q "Connected"; then
    warp-cli --accept-tos registration new 2>/dev/null || true
    sleep 2
fi

warp-cli --accept-tos mode warp 2>/dev/null || true
warp-cli --accept-tos connect 2>/dev/null || true
sleep 5

echo "[WARP] $(warp-cli --accept-tos status 2>/dev/null | head -1)"
IP=$(curl -s --max-time 10 https://cloudflare.com/cdn-cgi/trace 2>/dev/null | grep -oP 'ip=\K.*')
LOC=$(curl -s --max-time 10 https://cloudflare.com/cdn-cgi/trace 2>/dev/null | grep -oP 'loc=\K.*')
echo "[WARP] IP: ${IP:-unknown} | 地区: ${LOC:-unknown}"

exec "$@"
