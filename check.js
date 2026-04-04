const fs = require('fs/promises');
const http = require('http');
const https = require('https');
const path = require('path');

const P401 = /(^|\D)401(\D|$)|unauthorized|unauthenticated|token\s+expired|login\s+required|authentication\s+failed/i;
const PQUOTA = /(^|\D)(402|403|429)(\D|$)|quota|insufficient\s*quota|resource\s*exhausted|rate\s*limit|too\s+many\s+requests|payment\s+required|billing|credit|额度|用完|超限|上限|usage_limit_reached/i;

const DEFAULT_API_CALL_PROVIDERS = 'codex,openai,chatgpt';
const DEFAULT_API_CALL_URL = 'https://chatgpt.com/backend-api/wham/usage';
const DEFAULT_API_CALL_USER_AGENT = 'codex_cli_rs/0.76.0 (Debian 13.0.0; x86_64) WindowsTerminal';
const DEFAULT_API_CALL_ACCOUNT_ID = '141c5c10-0993-45c2-ad18-9a01ba2ab3e0';
const DEFAULT_API_CALL_MAX_PER_RUN = 9;
const DEFAULT_API_CALL_SLEEP_MIN = 5.0;
const DEFAULT_API_CALL_SLEEP_MAX = 10.0;
const AUTH_FILE_STATUS_METHODS = ['PATCH', 'PUT', 'POST'];

function pad2(value) {
    return String(value).padStart(2, '0');
}

function formatOffset(date) {
    const offsetMinutes = -date.getTimezoneOffset();
    const sign = offsetMinutes >= 0 ? '+' : '-';
    const absolute = Math.abs(offsetMinutes);
    const hours = Math.floor(absolute / 60);
    const minutes = absolute % 60;
    return `${sign}${pad2(hours)}${pad2(minutes)}`;
}

function getCurrentTime() {
    const now = new Date();
    return `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())} ${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())} ${formatOffset(now)}`;
}

function runId() {
    const now = new Date();
    return `${now.getUTCFullYear()}${pad2(now.getUTCMonth() + 1)}${pad2(now.getUTCDate())}T${pad2(now.getUTCHours())}${pad2(now.getUTCMinutes())}${pad2(now.getUTCSeconds())}Z`;
}

function stringifySafe(value) {
    try {
        return JSON.stringify(value);
    } catch (_error) {
        return String(value);
    }
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function requestRaw(urlObject, {method, headers, body, timeoutSeconds}) {
    return new Promise((resolve, reject) => {
        const transport = urlObject.protocol === 'https:' ? https : http;
        const req = transport.request(
            urlObject,
            {
                method,
                headers,
            },
            (res) => {
                const chunks = [];
                res.on('data', (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
                res.on('end', () => {
                    resolve({
                        statusCode: res.statusCode || 0,
                        headers: res.headers || {},
                        body: Buffer.concat(chunks),
                    });
                });
            }
        );

        req.setTimeout(timeoutSeconds * 1000, () => {
            req.destroy(new Error(`request timeout after ${timeoutSeconds}s`));
        });

        req.on('error', (error) => reject(error));

        if (body !== null && body !== undefined) {
            req.write(body);
        }
        req.end();
    });
}

async function api(base, key, method, apiPath, timeout = 20, query = null, expectJson = true, body = null, extraHeaders = null) {
    const urlObject = new URL(`${String(base).replace(/\/+$/, '')}/v0/management${apiPath}`);
    if (query && typeof query === 'object') {
        for (const [name, value] of Object.entries(query)) {
            if (value !== undefined && value !== null) {
                urlObject.searchParams.append(name, String(value));
            }
        }
    }

    const headers = {
        Authorization: `Bearer ${key}`,
        Accept: 'application/json',
        'User-Agent': 'cliproxyapi-cleaner/1.0',
        ...(extraHeaders || {}),
    };

    let payloadBuffer = null;
    if (body !== null && body !== undefined) {
        if (Buffer.isBuffer(body)) {
            payloadBuffer = body;
        } else if (typeof body === 'object') {
            payloadBuffer = Buffer.from(JSON.stringify(body), 'utf8');
            if (!headers['Content-Type']) {
                headers['Content-Type'] = 'application/json';
            }
        } else {
            payloadBuffer = Buffer.from(String(body), 'utf8');
            if (!headers['Content-Type']) {
                headers['Content-Type'] = 'application/json';
            }
        }
        headers['Content-Length'] = String(payloadBuffer.length);
    }

    let response;
    try {
        response = await requestRaw(urlObject, {
            method: String(method).toUpperCase(),
            headers,
            body: payloadBuffer,
            timeoutSeconds: timeout,
        });
    } catch (error) {
        throw new Error(`请求管理 API 失败: ${error.message || error}`);
    }

    if (expectJson) {
        const text = response.body.length ? response.body.toString('utf8') : '';
        let payload;
        try {
            payload = text ? JSON.parse(text) : {};
        } catch (_error) {
            payload = {raw: text};
        }
        return [response.statusCode, payload];
    }

    return [response.statusCode, response.body];
}

function extractErrorMessage(message) {
    try {
        if (typeof message === 'string' && message.trim().startsWith('{')) {
            const errorData = JSON.parse(message);
            if (Object.prototype.hasOwnProperty.call(errorData, 'error')) {
                const errorObject = errorData.error;
                if (errorObject && typeof errorObject === 'object' && !Array.isArray(errorObject)) {
                    const errorType = errorObject.type || '';
                    const errorMessage = errorObject.message || '';
                    return [errorType, errorMessage];
                }
                if (typeof errorObject === 'string') {
                    return ['error', errorObject];
                }
            }
            return [null, message];
        }
    } catch (_error) {
        return [null, message];
    }
    return [null, message];
}

function parseCsvSet(value) {
    if (!value) {
        return new Set();
    }
    return new Set(
        String(value)
            .split(',')
            .map((item) => item.trim().toLowerCase())
            .filter(Boolean)
    );
}

function simplifyReason(reason) {
    const text = String(reason || '').trim();
    if (!text) {
        return '';
    }
    if (!text.startsWith('{')) {
        return text.slice(0, 120);
    }

    let errorData;
    try {
        errorData = JSON.parse(text);
    } catch (_error) {
        return text.slice(0, 120);
    }

    if (!Object.prototype.hasOwnProperty.call(errorData, 'error')) {
        return text.slice(0, 120);
    }

    const errorObject = errorData.error;
    if (errorObject && typeof errorObject === 'object' && !Array.isArray(errorObject)) {
        const errorType = String(errorObject.type || '').trim();
        const errorMessage = String(errorObject.message || '').trim();
        if (errorType === 'usage_limit_reached') {
            return `usage_limit_reached: ${errorMessage}`.slice(0, 120);
        }
        return (errorType || errorMessage || text).slice(0, 120);
    }
    return String(errorObject).slice(0, 120);
}

function isDisabledItem(item) {
    const status = String(item.status || '').trim().toLowerCase();
    return Boolean(item.disabled) || status === 'disabled';
}

function classify(item) {
    const status = String(item.status || '').trim().toLowerCase();
    const message = String(item.status_message || '').trim();

    const [errorType] = extractErrorMessage(message);
    const text = `${status}\n${message}`.toLowerCase();

    if (P401.test(text)) {
        return ['delete_401', message || status || '401/unauthorized'];
    }

    if (errorType === 'usage_limit_reached' || text.includes('usage_limit_reached')) {
        return ['quota_exhausted', message || status || 'usage_limit_reached'];
    }

    if (PQUOTA.test(text)) {
        return ['quota_exhausted', message || status || 'quota'];
    }

    if (isDisabledItem(item)) {
        return ['disabled', message || status || 'disabled'];
    }

    if (Boolean(item.unavailable) || status === 'error') {
        return ['unavailable', message || status || 'error'];
    }

    return ['available', message || status || 'active'];
}

function shouldProbeApiCall(item, args) {
    if (!args.enableApiCallCheck && !args.enableDisabledRecovery) {
        return false;
    }

    const authIndex = String(item.auth_index || '').trim();
    if (!authIndex) {
        return false;
    }

    const provider = String(item.provider || item.type || '').trim().toLowerCase();
    if (args.apiCallProviderSet.size > 0 && !args.apiCallProviderSet.has(provider)) {
        return false;
    }

    const [initialKind] = classify(item);
    if (args.enableApiCallCheck && initialKind === 'available') {
        return true;
    }

    if (args.enableDisabledRecovery && isDisabledItem(item)) {
        return true;
    }

    return false;
}

function apiCallItemKey(item) {
    const authIndex = String(item.auth_index || '').trim();
    if (authIndex) {
        return `auth_index:${authIndex}`;
    }
    return `name:${String(item.name || item.id || '').trim()}`;
}

function buildApiCallPayload(item, args) {
    const headers = {
        Authorization: 'Bearer $TOKEN$',
        'Content-Type': 'application/json',
        'User-Agent': args.apiCallUserAgent,
    };
    if (args.apiCallAccountId.trim()) {
        headers['Chatgpt-Account-Id'] = args.apiCallAccountId.trim();
    }

    const payload = {
        authIndex: String(item.auth_index || '').trim(),
        method: args.apiCallMethod.toUpperCase(),
        url: args.apiCallUrl.trim(),
        header: headers,
    };
    if (args.apiCallBody) {
        payload.data = args.apiCallBody;
    }
    return payload;
}

function normalizeApiCallBody(body) {
    if (body === null || body === undefined) {
        return ['', null];
    }
    if (typeof body === 'string') {
        const text = body;
        const trimmed = text.trim();
        if (!trimmed) {
            return [text, null];
        }
        try {
            return [text, JSON.parse(trimmed)];
        } catch (_error) {
            return [text, text];
        }
    }
    try {
        return [JSON.stringify(body), body];
    } catch (_error) {
        return [String(body), body];
    }
}

function isLimitReachedWindow(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return false;
    }
    if (value.allowed === false) {
        return true;
    }
    if (value.limit_reached === true) {
        return true;
    }
    return false;
}

function classifyApiCallResponse(payload) {
    let nestedStatus = payload.status_code ?? payload.statusCode ?? 0;
    nestedStatus = Number.parseInt(nestedStatus, 10);
    if (Number.isNaN(nestedStatus)) {
        nestedStatus = 0;
    }

    const header = payload.header || payload.headers || {};
    const [bodyText, body] = normalizeApiCallBody(payload.body);

    let headerText;
    try {
        headerText = JSON.stringify(header);
    } catch (_error) {
        headerText = String(header);
    }

    let bodySignal = bodyText;
    if (body && typeof body === 'object') {
        try {
            bodySignal = JSON.stringify(body);
        } catch (_error) {
            bodySignal = bodyText;
        }
    }

    if (nestedStatus === 401) {
        return ['delete_401', bodySignal || `api-call status_code=${nestedStatus}`];
    }

    if (nestedStatus === 402 || nestedStatus === 403 || nestedStatus === 429) {
        return ['quota_exhausted', bodySignal || `api-call status_code=${nestedStatus}`];
    }

    if (body && typeof body === 'object' && !Array.isArray(body)) {
        const errorObject = body.error;
        if (errorObject && typeof errorObject === 'object' && !Array.isArray(errorObject)) {
            const errorType = String(errorObject.type || '').trim().toLowerCase();
            const errorMessage = String(errorObject.message || '').trim();
            const errorText = `${errorType}\n${errorMessage}`.toLowerCase();

            if (errorType === 'usage_limit_reached' || PQUOTA.test(errorText)) {
                return ['quota_exhausted', bodySignal || errorMessage || errorType];
            }

            if (P401.test(errorText)) {
                return ['delete_401', bodySignal || errorMessage || errorType];
            }
        }

        const rateLimit = body.rate_limit;
        const codeReviewRateLimit = body.code_review_rate_limit;
        if (isLimitReachedWindow(rateLimit) || isLimitReachedWindow(codeReviewRateLimit)) {
            return ['quota_exhausted', bodySignal || 'rate_limit_reached'];
        }

        if (nestedStatus === 200) {
            return [null, bodySignal || 'ok'];
        }
    }

    const fallbackText = `${nestedStatus}\n${headerText}\n${bodySignal}`.toLowerCase();
    if (P401.test(fallbackText)) {
        return ['delete_401', bodySignal || `api-call status_code=${nestedStatus}`];
    }

    if (nestedStatus !== 200 && PQUOTA.test(fallbackText)) {
        return ['quota_exhausted', bodySignal || `api-call status_code=${nestedStatus}`];
    }

    return [null, bodySignal || (nestedStatus ? `api-call status_code=${nestedStatus}` : 'ok')];
}

function isRecoverableDisabledProbe(probe) {
    if (!probe || typeof probe !== 'object') {
        return false;
    }
    if (probe.error) {
        return false;
    }
    if (probe.classification === 'delete_401' || probe.classification === 'quota_exhausted') {
        return false;
    }
    return Number.parseInt(probe.status_code, 10) === 200;
}

async function runApiCallProbe(args, item) {
    const requestPayload = buildApiCallPayload(item, args);
    const [code, payload] = await api(
        args.baseUrl,
        args.managementKey,
        'POST',
        '/api-call',
        args.timeout,
        null,
        true,
        requestPayload
    );
    if (code !== 200) {
        throw new Error(`调用 /api-call 失败: HTTP ${code} ${stringifySafe(payload)}`);
    }

    const [kind, reason] = classifyApiCallResponse(payload);
    const nestedStatusRaw = payload.status_code ?? payload.statusCode;
    let nestedStatus = Number.parseInt(nestedStatusRaw, 10);
    if (Number.isNaN(nestedStatus)) {
        nestedStatus = 0;
    }
    return {
        request: requestPayload,
        response: payload,
        classification: kind,
        reason,
        status_code: nestedStatus,
    };
}

function pickApiCallSleepSeconds(args) {
    if (args.apiCallSleep !== null && args.apiCallSleep !== undefined) {
        return Math.max(0, Number(args.apiCallSleep));
    }
    return args.apiCallSleepMin + Math.random() * (args.apiCallSleepMax - args.apiCallSleepMin);
}

async function runApiCallFullScan(args, files, counts) {
    if (!args.enableApiCallCheck && !args.enableDisabledRecovery) {
        counts['api-call候选数'] = 0;
        counts['api-call批次数'] = 0;
        return {};
    }

    if (args.apiCallScanCompleted) {
        counts['api-call候选数'] = 0;
        counts['api-call批次数'] = 0;
        console.log('[api-call] 当前进程已完成一次全量探测，本轮跳过');
        return {};
    }

    const eligible = files.filter((item) => shouldProbeApiCall(item, args));
    counts['api-call候选数'] = eligible.length;

    if (eligible.length === 0) {
        counts['api-call批次数'] = 0;
        args.apiCallScanCompleted = true;
        console.log('[api-call] 没有需要探测的候选账号，本次进程不再执行 api-call');
        return {};
    }

    const batchSize = Math.max(1, Math.min(Number.parseInt(args.apiCallMaxPerRun, 10), DEFAULT_API_CALL_MAX_PER_RUN));
    const batchCount = Math.ceil(eligible.length / batchSize);
    counts['api-call批次数'] = batchCount;
    const sleepDesc = args.apiCallSleep !== null && args.apiCallSleep !== undefined
        ? `固定 ${Number(args.apiCallSleep).toFixed(1)} 秒`
        : `随机 ${Number(args.apiCallSleepMin).toFixed(1)}-${Number(args.apiCallSleepMax).toFixed(1)} 秒`;
    console.log(
        `[api-call] 已开启全量探测，本次运行将探测 ${eligible.length} 个候选账号，共 ${batchCount} 批，每批最多 ${batchSize} 个，批次间隔 ${sleepDesc}`
    );

    const probeResults = {};
    let probedTotal = 0;

    for (let batchIndex = 0; batchIndex < batchCount; batchIndex += 1) {
        const start = batchIndex * batchSize;
        const batch = eligible.slice(start, start + batchSize);
        console.log(`[api-call批次 ${batchIndex + 1}/${batchCount}] 并发探测 ${batch.length} 个账号`);

        await Promise.all(
            batch.map(async (item) => {
                const name = String(item.name || item.id || '').trim();
                const provider = String(item.provider || item.type || '').trim();
                const authIndex = item.auth_index;

                try {
                    const probe = await runApiCallProbe(args, item);
                    counts['api-call已探测'] += 1;
                    probedTotal += 1;
                    const currentIndex = probedTotal;
                    probeResults[apiCallItemKey(item)] = probe;
                    const classification = probe.classification || 'ok';
                    if (classification === 'delete_401') {
                        counts['api-call发现401'] += 1;
                    } else if (classification === 'quota_exhausted') {
                        counts['api-call发现配额耗尽'] += 1;
                    }
                    console.log(
                        `  [api-call完成 ${currentIndex}/${eligible.length}] ${name} provider=${provider} auth_index=${authIndex} result=${classification}`
                    );
                } catch (error) {
                    counts['api-call已探测'] += 1;
                    probedTotal += 1;
                    const currentIndex = probedTotal;
                    counts['api-call探测失败'] += 1;
                    probeResults[apiCallItemKey(item)] = {error: error.message || String(error)};
                    console.log(
                        `  [api-call完成 ${currentIndex}/${eligible.length}] ${name} provider=${provider} auth_index=${authIndex} result=error error=${error.message || error}`
                    );
                }
            })
        );

        if (batchIndex + 1 < batchCount) {
            const sleepSeconds = pickApiCallSleepSeconds(args);
            if (sleepSeconds > 0) {
                console.log(`[api-call批次 ${batchIndex + 1}/${batchCount}] 整批完成，等待 ${sleepSeconds.toFixed(1)} 秒后继续下一批`);
                await sleep(sleepSeconds * 1000);
            }
        }
    }

    args.apiCallScanCompleted = true;
    console.log('[api-call] 本次运行已完成全部候选账号探测，后续轮次不再重复探测');
    return probeResults;
}

async function updateAuthFileDisabled(args, name, disabled) {
    const payload = {name, disabled: Boolean(disabled)};
    const attempts = [];
    for (const method of AUTH_FILE_STATUS_METHODS) {
        const [code, response] = await api(
            args.baseUrl,
            args.managementKey,
            method,
            '/auth-files/status',
            args.timeout,
            null,
            true,
            payload
        );
        attempts.push({method, code, response});
        if (code >= 200 && code < 300) {
            return attempts[attempts.length - 1];
        }
        if (![404, 405, 501].includes(code)) {
            break;
        }
    }
    throw new Error(`更新 auth-files/status 失败: ${stringifySafe(attempts)}`);
}

async function disableAuthFile(args, name) {
    return updateAuthFileDisabled(args, name, true);
}

async function enableAuthFile(args, name) {
    return updateAuthFileDisabled(args, name, false);
}

async function runCheck(args) {
    const [code, payload] = await api(args.baseUrl, args.managementKey, 'GET', '/auth-files', args.timeout);
    if (code !== 200) {
        console.error(`[错误] 获取 auth-files 失败: HTTP ${code} ${stringifySafe(payload)}`);
        return null;
    }

    const files = payload.files || [];
    if (!Array.isArray(files)) {
        console.error(`[错误] auth-files 返回异常: ${stringifySafe(payload)}`);
        return null;
    }

    const rid = runId();
    const backupRoot = path.join('backups', 'cliproxyapi-auth-cleaner', rid);
    const reportRoot = path.join('reports', 'cliproxyapi-auth-cleaner');
    await fs.mkdir(reportRoot, {recursive: true});

    const counts = {
        '检查总数': 0,
        '可用账号': 0,
        '配额耗尽': 0,
        '已禁用': 0,
        '不可用': 0,
        'api-call候选数': 0,
        'api-call批次数': 0,
        'api-call已探测': 0,
        'api-call发现401': 0,
        'api-call发现配额耗尽': 0,
        'api-call探测失败': 0,
        '待删除401': 0,
        '已删除': 0,
        '备份失败': 0,
        '删除失败': 0,
        '额度账号已禁用': 0,
        '禁用失败': 0,
        '待恢复启用': 0,
        '已恢复启用': 0,
        '恢复失败': 0,
    };
    const results = [];

    console.log(`[${getCurrentTime()}] 开始检查 ${files.length} 个账号`);
    const probeResults = await runApiCallFullScan(args, files, counts);

    for (const item of files) {
        counts['检查总数'] += 1;
        const name = String(item.name || item.id || '').trim();
        const provider = String(item.provider || item.type || '').trim();
        const itemDisabled = isDisabledItem(item);
        let [kind, reason] = classify(item);

        const row = {
            name,
            provider,
            auth_index: item.auth_index,
            status: item.status,
            status_message: item.status_message,
            disabled: item.disabled,
            unavailable: item.unavailable,
            runtime_only: item.runtime_only,
            source: item.source,
        };

        const probe = probeResults[apiCallItemKey(item)];
        if (probe !== undefined) {
            row.api_call_probe = probe;
            if (probe.classification === 'delete_401') {
                kind = 'delete_401';
                reason = probe.reason || reason;
            } else if (probe.classification === 'quota_exhausted') {
                kind = 'quota_exhausted';
                reason = probe.reason || reason;
            } else if (args.enableDisabledRecovery && itemDisabled && isRecoverableDisabledProbe(probe)) {
                kind = 'disabled_recovered';
                reason = probe.reason || reason || 'api-call status_code=200';
            }
        }

        row.final_classification = kind;
        row.reason = reason;
        const displayReason = simplifyReason(reason);

        if (kind === 'available') {
            counts['可用账号'] += 1;
        } else if (kind === 'quota_exhausted') {
            counts['配额耗尽'] += 1;
            console.log(`[配额耗尽] ${name} provider=${provider} reason=${displayReason}`);
            if (args.dryRun) {
                row.disable_result = 'dry_run_skip';
                console.log('  [模拟运行] 将调用 /auth-files/status 设置 disabled=true');
            } else if (!name) {
                counts['禁用失败'] += 1;
                row.disable_result = 'skip_no_name';
                row.disable_error = '缺少 name，无法调用 /auth-files/status';
                console.log('  [禁用失败] 缺少 name，无法更新状态');
            } else {
                try {
                    const disableResponse = await disableAuthFile(args, name);
                    counts['额度账号已禁用'] += 1;
                    row.disable_result = 'disabled_true';
                    row.disable_response = disableResponse;
                    console.log(`  [已禁用] method=${disableResponse.method} HTTP ${disableResponse.code}`);
                } catch (error) {
                    counts['禁用失败'] += 1;
                    row.disable_result = 'disable_failed';
                    row.disable_error = error.message || String(error);
                    console.log(`  [禁用失败] ${error.message || error}`);
                }
            }
        } else if (kind === 'disabled_recovered') {
            counts['待恢复启用'] += 1;
            console.log(`[已禁用-额度恢复可启用] ${name} provider=${provider} reason=${displayReason}`);
            if (args.dryRun) {
                row.recover_result = 'dry_run_skip';
                console.log('  [模拟运行] 将调用 /auth-files/status 设置 disabled=false');
            } else if (!name) {
                counts['恢复失败'] += 1;
                row.recover_result = 'skip_no_name';
                row.recover_error = '缺少 name，无法调用 /auth-files/status';
                console.log('  [恢复失败] 缺少 name，无法更新状态');
            } else {
                try {
                    const recoverResponse = await enableAuthFile(args, name);
                    counts['已恢复启用'] += 1;
                    row.recover_result = 'disabled_false';
                    row.recover_response = recoverResponse;
                    console.log(`  [已恢复启用] method=${recoverResponse.method} HTTP ${recoverResponse.code}`);
                } catch (error) {
                    counts['恢复失败'] += 1;
                    row.recover_result = 'recover_failed';
                    row.recover_error = error.message || String(error);
                    console.log(`  [恢复失败] ${error.message || error}`);
                }
            }
        } else if (kind === 'disabled') {
            counts['已禁用'] += 1;
            console.log(`[已禁用-不删除] ${name} provider=${provider}`);
        } else if (kind === 'unavailable') {
            counts['不可用'] += 1;
            console.log(`[不可用-不删除] ${name} provider=${provider} reason=${displayReason}`);
        } else if (kind === 'delete_401') {
            counts['待删除401'] += 1;
            console.log(`[待删除-401认证失败] ${name} provider=${provider} reason=${displayReason}`);

            if (args.dryRun) {
                row.delete_result = 'dry_run_skip';
                console.log('  [模拟运行] 将删除此文件');
            } else {
                const runtimeOnly = Boolean(item.runtime_only);
                const source = String(item.source || '').trim().toLowerCase();
                if (runtimeOnly || (source && source !== 'file')) {
                    counts['备份失败'] += 1;
                    row.delete_result = 'skip_runtime_only';
                    row.delete_error = 'runtime_only/source!=file，管理 API 无法删除';
                    console.log('  [跳过] runtime_only 或非磁盘文件，无法通过 /auth-files 删除');
                } else if (!name.toLowerCase().endsWith('.json')) {
                    counts['备份失败'] += 1;
                    row.delete_result = 'skip_no_json_name';
                    row.delete_error = '不是标准 .json 文件名，默认不删';
                    console.log('  [跳过] 不是 .json 文件');
                } else {
                    try {
                        const [downloadCode, raw] = await api(
                            args.baseUrl,
                            args.managementKey,
                            'GET',
                            '/auth-files/download',
                            args.timeout,
                            {name},
                            false
                        );
                        if (downloadCode !== 200) {
                            throw new Error(`下载 auth 文件失败: ${name} HTTP ${downloadCode}`);
                        }
                        await fs.mkdir(backupRoot, {recursive: true});
                        const backupPath = path.join(backupRoot, path.basename(name));
                        await fs.writeFile(backupPath, raw);
                        row.backup_path = backupPath;

                        const [deleteCode, deletePayload] = await api(
                            args.baseUrl,
                            args.managementKey,
                            'DELETE',
                            '/auth-files',
                            args.timeout,
                            {name},
                            true
                        );
                        if (deleteCode !== 200) {
                            throw new Error(`删除 auth 文件失败: ${name} HTTP ${deleteCode} ${stringifySafe(deletePayload)}`);
                        }
                        counts['已删除'] += 1;
                        row.delete_result = 'deleted';
                        row.delete_response = deletePayload;
                        console.log(`  [已删除] 备份路径: ${row.backup_path}`);
                    } catch (error) {
                        counts['删除失败'] += 1;
                        row.delete_result = 'delete_failed';
                        row.delete_error = error.message || String(error);
                        console.log(`  [删除失败] ${error.message || error}`);
                    }
                }
            }
        }

        results.push(row);
    }

    const report = {
        run_id: rid,
        base_url: args.baseUrl,
        dry_run: args.dryRun,
        api_call: {
            enabled: args.enableApiCallCheck || args.enableDisabledRecovery,
            scan_available_accounts: args.enableApiCallCheck,
            recover_disabled_accounts: args.enableDisabledRecovery,
            completed_in_this_process: Boolean(args.apiCallScanCompleted),
            providers: args.apiCallProviders,
            url: args.apiCallUrl,
            batch_size: args.apiCallMaxPerRun,
            sleep_fixed: args.apiCallSleep,
            sleep_min: args.apiCallSleepMin,
            sleep_max: args.apiCallSleepMax,
        },
        results,
        summary: counts,
    };
    const reportPath = path.join(reportRoot, `report-${rid}.json`);
    await fs.writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');

    console.log(`\n${'='.repeat(60)}`);
    console.log('【统计结果】');
    console.log('='.repeat(60));
    for (const [key, value] of Object.entries(counts)) {
        console.log(`  ${key}: ${value}`);
    }

    console.log('\n【操作说明】');
    if (args.dryRun) {
        console.log('  ✅ 模拟运行模式 - 没有实际删除或禁用任何账号');
        if (counts['待删除401'] > 0) {
            console.log(`  📝 发现 ${counts['待删除401']} 个 401 认证失败账号（去掉 --dry-run 后会备份并删除）`);
        }
        if (counts['配额耗尽'] > 0) {
            console.log(`  📝 发现 ${counts['配额耗尽']} 个额度耗尽账号（去掉 --dry-run 后会调用 /auth-files/status 禁用）`);
        }
        if (counts['待恢复启用'] > 0) {
            console.log(`  📝 发现 ${counts['待恢复启用']} 个已禁用但额度恢复账号（去掉 --dry-run 后会调用 /auth-files/status 启用）`);
        }
    } else {
        console.log(`  ✅ 已删除 ${counts['已删除']} 个 401 认证失败账号`);
        console.log(`  ✅ 已禁用 ${counts['额度账号已禁用']} 个额度耗尽账号`);
        console.log(`  ✅ 已恢复启用 ${counts['已恢复启用']} 个已禁用账号`);
        if (counts['删除失败'] > 0) {
            console.log(`  ⚠️  有 ${counts['删除失败']} 个账号删除失败，请查看报告`);
        }
        if (counts['禁用失败'] > 0) {
            console.log(`  ⚠️  有 ${counts['禁用失败']} 个额度账号禁用失败，请查看报告`);
        }
        if (counts['恢复失败'] > 0) {
            console.log(`  ⚠️  有 ${counts['恢复失败']} 个已禁用账号恢复失败，请查看报告`);
        }
    }

    console.log('\n【报告文件】');
    console.log(`  📄 ${reportPath}`);
    console.log('='.repeat(60));

    return counts;
}

const OPTION_DEFS = {
    '--base-url': {
        key: 'baseUrl',
        type: 'string',
        defaultValue: 'http://127.0.0.1:8317',
        help: '管理 API 的基础地址',
    },
    '--management-key': {
        key: 'managementKey',
        type: 'string',
        defaultValue: '',
        help: '管理 API 的 Bearer token',
    },
    '--timeout': {
        key: 'timeout',
        type: 'int',
        defaultValue: Number.parseInt(process.env.CLIPROXY_TIMEOUT || '20', 10),
        help: '管理 API 请求超时秒数',
    },
    '--enable-api-call-check': {
        key: 'enableApiCallCheck',
        type: 'boolean',
        defaultValue: false,
        help: '开启 /api-call 全量探测；本次脚本运行只会完整探测一遍',
    },
    '--enable-disabled-recovery': {
        key: 'enableDisabledRecovery',
        type: 'boolean',
        defaultValue: true,
        help: '探测 disabled 账号额度；若恢复则自动设置 disabled=false',
    },
    '--api-call-url': {
        key: 'apiCallUrl',
        type: 'string',
        defaultValue: process.env.CLIPROXY_API_CALL_URL || DEFAULT_API_CALL_URL,
        help: '主动探测时调用的上游 URL',
    },
    '--api-call-method': {
        key: 'apiCallMethod',
        type: 'string',
        defaultValue: process.env.CLIPROXY_API_CALL_METHOD || 'GET',
        help: '主动探测时使用的 HTTP 方法',
    },
    '--api-call-account-id': {
        key: 'apiCallAccountId',
        type: 'string',
        defaultValue: process.env.CLIPROXY_API_CALL_ACCOUNT_ID || DEFAULT_API_CALL_ACCOUNT_ID,
        help: '主动探测时附带的 Chatgpt-Account-Id',
    },
    '--api-call-user-agent': {
        key: 'apiCallUserAgent',
        type: 'string',
        defaultValue: process.env.CLIPROXY_API_CALL_USER_AGENT || DEFAULT_API_CALL_USER_AGENT,
        help: '主动探测时附带的 User-Agent',
    },
    '--api-call-body': {
        key: 'apiCallBody',
        type: 'string',
        defaultValue: process.env.CLIPROXY_API_CALL_BODY || '',
        help: '主动探测时透传到 api-call 的 data 字段',
    },
    '--api-call-providers': {
        key: 'apiCallProviders',
        type: 'string',
        defaultValue: process.env.CLIPROXY_API_CALL_PROVIDERS || DEFAULT_API_CALL_PROVIDERS,
        help: '哪些 provider 需要做 /api-call 主动探测，逗号分隔；留空表示全部',
    },
    '--api-call-max-per-run': {
        key: 'apiCallMaxPerRun',
        type: 'int',
        defaultValue: Number.parseInt(process.env.CLIPROXY_API_CALL_MAX_PER_RUN || String(DEFAULT_API_CALL_MAX_PER_RUN), 10),
        help: '每批最多探测多少个账号，最大 9',
    },
    '--api-call-sleep': {
        key: 'apiCallSleep',
        type: 'float',
        defaultValue: null,
        help: '固定批次等待秒数；如不设置则使用随机等待',
    },
    '--api-call-sleep-min': {
        key: 'apiCallSleepMin',
        type: 'float',
        defaultValue: Number.parseFloat(process.env.CLIPROXY_API_CALL_SLEEP_MIN || String(DEFAULT_API_CALL_SLEEP_MIN)),
        help: '批次随机等待最小秒数',
    },
    '--api-call-sleep-max': {
        key: 'apiCallSleepMax',
        type: 'float',
        defaultValue: Number.parseFloat(process.env.CLIPROXY_API_CALL_SLEEP_MAX || String(DEFAULT_API_CALL_SLEEP_MAX)),
        help: '批次随机等待最大秒数',
    },
    '--dry-run': {
        key: 'dryRun',
        type: 'boolean',
        defaultValue: false,
        help: '模拟运行，不实际删除或禁用',
    },
    '--interval': {
        key: 'interval',
        type: 'int',
        defaultValue: 60,
        help: '检测间隔时间（秒），默认 60 秒',
    },
    '--once': {
        key: 'once',
        type: 'boolean',
        defaultValue: false,
        help: '只执行一次，不循环',
    },
};

function parseValue(rawValue, type, flag) {
    if (type === 'string') {
        return rawValue;
    }
    if (type === 'int') {
        const value = Number.parseInt(rawValue, 10);
        if (Number.isNaN(value)) {
            throw new Error(`${flag} 需要整数值`);
        }
        return value;
    }
    if (type === 'float') {
        const value = Number.parseFloat(rawValue);
        if (Number.isNaN(value)) {
            throw new Error(`${flag} 需要数字值`);
        }
        return value;
    }
    throw new Error(`未知参数类型: ${type}`);
}

function buildDefaultArgs() {
    const args = {};
    for (const option of Object.values(OPTION_DEFS)) {
        args[option.key] = option.defaultValue;
    }
    return args;
}

function printUsage() {
    console.log('用法: node check.js [options]');
    console.log('');
    console.log('选项:');
    console.log('  -h, --help                       显示帮助');
    for (const [flag, option] of Object.entries(OPTION_DEFS)) {
        const suffix = option.type === 'boolean' ? '' : ` <${option.type}>`;
        console.log(`  ${flag.padEnd(30)}${suffix.padEnd(10)}${option.help}`);
    }
}

function parseCliArgs(argv) {
    const args = buildDefaultArgs();

    for (let index = 0; index < argv.length; index += 1) {
        const token = argv[index];

        if (token === '--help' || token === '-h') {
            args.help = true;
            continue;
        }

        if (!token.startsWith('--')) {
            throw new Error(`未知参数: ${token}`);
        }

        let flag = token;
        let inlineValue;
        const equalIndex = token.indexOf('=');
        if (equalIndex !== -1) {
            flag = token.slice(0, equalIndex);
            inlineValue = token.slice(equalIndex + 1);
        }

        const definition = OPTION_DEFS[flag];
        if (!definition) {
            throw new Error(`未知参数: ${flag}`);
        }

        if (definition.type === 'boolean') {
            args[definition.key] = true;
            continue;
        }

        let rawValue = inlineValue;
        if (rawValue === undefined) {
            index += 1;
            if (index >= argv.length) {
                throw new Error(`${flag} 缺少参数值`);
            }
            rawValue = argv[index];
        }

        args[definition.key] = parseValue(rawValue, definition.type, flag);
    }

    args.apiCallProviderSet = parseCsvSet(args.apiCallProviders);
    args.apiCallMaxPerRun = Math.max(0, Math.min(Number.parseInt(args.apiCallMaxPerRun, 10), DEFAULT_API_CALL_MAX_PER_RUN));
    if (args.apiCallSleep !== null) {
        args.apiCallSleep = Math.max(0, Number(args.apiCallSleep));
    }
    args.apiCallSleepMin = Math.max(0, Number(args.apiCallSleepMin));
    args.apiCallSleepMax = Math.max(args.apiCallSleepMin, Number(args.apiCallSleepMax));
    args.apiCallScanCompleted = false;

    return args;
}

async function main() {
    let args;
    try {
        args = parseCliArgs(process.argv.slice(2));
    } catch (error) {
        console.error(`❌ ${error.message || error}`);
        console.error('使用 --help 查看可用参数');
        return 2;
    }

    if (args.help) {
        printUsage();
        return 0;
    }

    if (!String(args.managementKey || '').trim()) {
        console.error('❌ 缺少 management key：请先设置 CLIPROXY_MANAGEMENT_KEY');
        return 2;
    }

    console.log(`\n${'='.repeat(60)}`);
    console.log('【CLIProxyAPI 清理工具】');
    console.log('='.repeat(60));
    console.log('  🎯 清理目标: 删除 401 认证失败账号 + 禁用额度耗尽账号');
    if (args.enableApiCallCheck || args.enableDisabledRecovery) {
        const providersDesc = args.apiCallProviders.trim() ? args.apiCallProviders : '全部 provider';
        const sleepDesc = args.apiCallSleep !== null
            ? `固定 ${Number(args.apiCallSleep).toFixed(1)} 秒`
            : `随机 ${Number(args.apiCallSleepMin).toFixed(1)}-${Number(args.apiCallSleepMax).toFixed(1)} 秒`;
        console.log('  🔎 主动探测: 已开启 /v0/management/api-call');
        console.log(`     - 可用账号探测: ${args.enableApiCallCheck ? '开启' : '关闭'}`);
        console.log(`     - 禁用账号恢复探测: ${args.enableDisabledRecovery ? '开启' : '关闭'}`);
        console.log(`     - 上游 URL: ${args.apiCallUrl}`);
        console.log(`     - 适用 provider: ${providersDesc}`);
        console.log(`     - 单批最多: ${args.apiCallMaxPerRun} 个`);
        console.log(`     - 批次间隔: ${sleepDesc}`);
        console.log('     - 探测策略: 本次运行只完整扫描一遍，后续轮次不再重复');
    } else {
        console.log('  🔎 主动探测: 未开启 /v0/management/api-call');
    }
    if (args.enableDisabledRecovery) {
        console.log('  🛡️  保护机制: 仅删除401；配额耗尽账号会禁用；已禁用账号仅在探测健康时恢复启用');
    } else {
        console.log('  🛡️  保护机制: 不会删除配额耗尽、禁用、不可用账号，只会禁用额度耗尽账号');
    }
    if (args.dryRun) {
        console.log('  🔍 运行模式: 模拟运行（不会实际删除或禁用）');
    } else {
        console.log('  ⚡ 运行模式: 实际运行（将删除/禁用符合条件的账号）');
    }
    console.log(`${'='.repeat(60)}\n`);

    if (args.once) {
        await runCheck(args);
        return 0;
    }

    console.log(`🔄 自动循环检测模式，间隔 ${args.interval} 秒`);
    console.log('💡 提示: 按 Ctrl+C 停止程序\n');

    let loopCount = 0;
    try {
        while (true) {
            loopCount += 1;
            console.log(`\n${'🔵'.repeat(30)}`);
            console.log(`【第 ${loopCount} 次检测】${getCurrentTime()}`);
            console.log('🔵'.repeat(30));

            try {
                await runCheck(args);
            } catch (error) {
                console.log(`❌ 检测过程中发生异常: ${error.message || error}`);
            }

            console.log(`\n⏰ 等待 ${args.interval} 秒后进行下一次检测...`);
            await sleep(args.interval * 1000);
        }
    } catch (error) {
        if (error && error.name === 'AbortError') {
            throw error;
        }
        if (error && error.code === 'SIGINT') {
            console.log(`\n\n🛑 用户中断程序，共执行 ${loopCount} 次检测`);
            return 0;
        }
        throw error;
    }
}

process.on('SIGINT', () => {
    console.log('\n\n🛑 用户中断程序');
    process.exit(0);
});

main()
    .then((code) => {
        process.exitCode = code;
    })
    .catch((error) => {
        console.error(`❌ ${error.message || error}`);
        process.exitCode = 1;
    });
