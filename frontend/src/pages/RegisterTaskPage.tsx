import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Button,
  Tag,
  Space,
  Typography,
  Descriptions,
} from 'antd'
import {
  PlayCircleOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
} from '@ant-design/icons'
import { ChatGPTRegistrationModeSwitch } from '@/components/ChatGPTRegistrationModeSwitch'
import { TaskLogPanel } from '@/components/TaskLogPanel'
import { usePersistentChatGPTRegistrationMode } from '@/hooks/usePersistentChatGPTRegistrationMode'
import { buildChatGPTRegistrationRequestAdapter } from '@/lib/chatgptRegistrationRequestAdapter'
import { getExecutorOptions, normalizeExecutorForPlatform } from '@/lib/platformExecutorOptions'
import { apiFetch } from '@/lib/utils'

const { Text } = Typography

export default function RegisterTaskPage() {
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [task, setTask] = useState<any>(null)
  const [polling, setPolling] = useState(false)
  const [mailboxServices, setMailboxServices] = useState<any[]>([])
  const [cpaRunning, setCpaRunning] = useState(false)
  const [cpaOutput, setCpaOutput] = useState('')
  const [lastSubmittedProxy, setLastSubmittedProxy] = useState('')
  const [proxyValue, setProxyValue] = useState('')
  const { mode: chatgptRegistrationMode, setMode: setChatgptRegistrationMode } =
    usePersistentChatGPTRegistrationMode()

  useEffect(() => {
    apiFetch('/config').then((cfg) => {
      const currentPlatform = form.getFieldValue('platform') || 'trae'
      form.setFieldsValue({
        executor_type: normalizeExecutorForPlatform(currentPlatform, cfg.default_executor),
        captcha_solver: cfg.default_captcha_solver || 'yescaptcha',
        yescaptcha_key: cfg.yescaptcha_key || '',
        smstome_cookie: cfg.smstome_cookie || '',
        smstome_country_slugs: cfg.smstome_country_slugs || '',
        smstome_phone_attempts: cfg.smstome_phone_attempts || '',
        smstome_otp_timeout_seconds: cfg.smstome_otp_timeout_seconds || '',
        smstome_poll_interval_seconds: cfg.smstome_poll_interval_seconds || '',
        smstome_sync_max_pages_per_country: cfg.smstome_sync_max_pages_per_country || '',
      })
      setProxyValue(cfg.default_proxy || '')
    })
    apiFetch('/mailboxes')
      .then((items) => {
        setMailboxServices((items || []).filter((item: any) => item.is_active))
      })
      .catch(() => {
        setMailboxServices([])
      })
  }, [form])

  const submit = async () => {
    const validatedValues = await form.validateFields()
    const values = { ...form.getFieldsValue(true), ...validatedValues }
    const resolvedProxy = (proxyValue || '').trim()
    values.proxy = resolvedProxy || null
    console.log('[RegisterTaskPage] submit proxy =', values.proxy)
    setLastSubmittedProxy(values.proxy || '')
    const registerExtra = {
      mailbox_service_id: values.mailbox_service_id,
      proxy: values.proxy,
      yescaptcha_key: values.yescaptcha_key,
      solver_url: values.solver_url,
      smstome_cookie: values.smstome_cookie,
      smstome_country_slugs: values.smstome_country_slugs,
      smstome_phone_attempts: values.smstome_phone_attempts,
      smstome_otp_timeout_seconds: values.smstome_otp_timeout_seconds,
      smstome_poll_interval_seconds: values.smstome_poll_interval_seconds,
      smstome_sync_max_pages_per_country: values.smstome_sync_max_pages_per_country,
    }
    const chatgptRegistrationRequestAdapter =
      buildChatGPTRegistrationRequestAdapter(
        values.platform,
        chatgptRegistrationMode,
      )
    const adaptedRegisterExtra = chatgptRegistrationRequestAdapter
      ? chatgptRegistrationRequestAdapter.extendExtra(registerExtra)
      : registerExtra

    const res = await apiFetch('/tasks/register', {
      method: 'POST',
      body: JSON.stringify({
        platform: values.platform,
        email: values.email || null,
        password: values.password || null,
        count: values.count,
        register_delay_seconds: values.register_delay_seconds || 0,
        proxy: values.proxy || null,
        executor_type: values.executor_type,
        captcha_solver: values.captcha_solver,
        extra: adaptedRegisterExtra,
      }),
    })
    setTask(res)
    setPolling(true)
    pollTask(res.task_id)
  }

  const pollTask = async (id: string) => {
    const interval = setInterval(async () => {
      const t = await apiFetch(`/tasks/${id}`)
      setTask(t)
      if (t.status === 'done' || t.status === 'failed' || t.status === 'stopped') {
        clearInterval(interval)
        setPolling(false)
        if (t.cashier_urls && t.cashier_urls.length > 0) {
          t.cashier_urls.forEach((url: string) => window.open(url, '_blank'))
        }
      }
    }, 2000)
  }

  const captchaSolver = Form.useWatch('captcha_solver', form)
  const platform = Form.useWatch('platform', form)
  const executorOptions = getExecutorOptions(platform)

  const quickRunCpaCheck = async () => {
    setCpaRunning(true)
    try {
      const res = await apiFetch('/cpa-monitor/run', {
        method: 'POST',
        body: JSON.stringify({ once: true, dry_run: false, enable_api_call_check: false, enable_disabled_recovery: true }),
      })
      setCpaOutput([res?.stdout, res?.stderr].filter(Boolean).join('\n'))
    } finally {
      setCpaRunning(false)
    }
  }

  useEffect(() => {
    const currentExecutor = form.getFieldValue('executor_type')
    const normalizedExecutor = normalizeExecutorForPlatform(platform, currentExecutor)
    if (currentExecutor !== normalizedExecutor) {
      form.setFieldValue('executor_type', normalizedExecutor)
    }
  }, [form, platform])

  return (
    <div style={{ maxWidth: 800 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 'bold', margin: 0 }}>注册任务</h1>
        <p style={{ color: '#7a8ba3', marginTop: 4 }}>创建账号自动注册任务</p>
      </div>

      <Form form={form} layout="vertical" onFinish={submit} initialValues={{
        platform: 'trae',
        executor_type: 'protocol',
        captcha_solver: 'yescaptcha',
        count: 1,
        register_delay_seconds: 0,
        solver_url: 'http://localhost:8889',
      }}>
        <Card title="基本配置" style={{ marginBottom: 16 }}>
          {(platform === 'chatgpt' || platform === 'codex') && (
            <div style={{ marginBottom: 16, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Button onClick={() => navigate('/cpa-monitor')}>打开 CPA 监控台</Button>
              <Button loading={cpaRunning} onClick={quickRunCpaCheck}>快速运行检查</Button>
            </div>
          )}
          <Form.Item name="platform" label="平台" rules={[{ required: true }]}> 
            <Select
              options={[
                { value: 'chatgpt', label: 'ChatGPT' },
                { value: 'codex', label: 'Codex' },
                { value: 'trae', label: 'Trae.ai' },
                { value: 'cursor', label: 'Cursor' },
                { value: 'kiro', label: 'Kiro' },
                { value: 'grok', label: 'Grok' },
                { value: 'tavily', label: 'Tavily' },
                { value: 'openblocklabs', label: 'OpenBlockLabs' },
              ]}
            />
          </Form.Item>
          <Form.Item name="executor_type" label="执行器" rules={[{ required: true }]}>
            <Select options={executorOptions} />
          </Form.Item>
          <Form.Item name="captcha_solver" label="验证码" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'yescaptcha', label: 'YesCaptcha' },
                { value: 'local_solver', label: '本地 Solver (Camoufox)' },
                { value: 'manual', label: '手动' },
              ]}
            />
          </Form.Item>
          <Space style={{ width: '100%' }}>
            <Form.Item name="count" label="批量数量" style={{ flex: 1 }}>
              <Input type="number" min={1} />
            </Form.Item>
            <Form.Item name="register_delay_seconds" label="每个注册延迟(秒)" style={{ flex: 1 }}>
              <InputNumber min={0} precision={1} step={0.5} style={{ width: '100%' }} placeholder="0" />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }}>
            <div style={{ flex: 1 }}>
              <div style={{ marginBottom: 8, fontWeight: 500 }}>代理 (可选)</div>
              <Input
                id="proxy"
                value={proxyValue}
                placeholder="http://user:pass@host:port"
                onChange={(e) => setProxyValue(e.target.value)}
              />
            </div>
          </Space>
          {platform === 'codex' ? (
            <div style={{ marginBottom: 12 }}>
              <Text type="secondary" style={{ display: 'block' }}>
                当前表单代理: {proxyValue || '(空)'}
              </Text>
              <Text type="secondary" style={{ display: 'block' }}>
                最近一次提交代理: {lastSubmittedProxy || '(空)'}
              </Text>
            </div>
          ) : null}
          {platform === 'chatgpt' && (
            <Form.Item label="ChatGPT Token 方案">
              <ChatGPTRegistrationModeSwitch
                mode={chatgptRegistrationMode}
                onChange={setChatgptRegistrationMode}
              />
            </Form.Item>
          )}
        </Card>

        <Card title="邮箱配置" style={{ marginBottom: 16 }}>
          <Form.Item
            name="mailbox_service_id"
            label="邮箱服务实例"
            rules={[{ required: true, message: '请选择邮箱服务实例' }]}
            extra="注册时将直接使用这里选择的邮箱服务实例配置。"
          >
            <Select
              allowClear
              placeholder="选择已配置的邮箱服务实例"
              options={mailboxServices.map((item) => ({
                value: item.id,
                label: `${item.name} (${item.provider})`,
              }))}
            />
          </Form.Item>
        </Card>

        {platform === 'chatgpt' && (
          <Card title="ChatGPT 手机验证" style={{ marginBottom: 16 }}>
            <Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
              仅在 OAuth 流程进入 `add_phone` 时使用，用于自动取号并轮询短信验证码。
            </Text>
            <Form.Item name="smstome_cookie" label="SMSToMe Cookie">
              <Input.Password placeholder="cf_clearance=...; PHPSESSID=..." />
            </Form.Item>
            <Form.Item name="smstome_country_slugs" label="国家列表">
              <Input placeholder="united-kingdom,poland,finland" />
            </Form.Item>
            <Form.Item name="smstome_phone_attempts" label="手机号尝试次数">
              <Input placeholder="3" />
            </Form.Item>
            <Form.Item name="smstome_otp_timeout_seconds" label="短信等待秒数">
              <Input placeholder="45" />
            </Form.Item>
            <Form.Item name="smstome_poll_interval_seconds" label="轮询间隔秒数">
              <Input placeholder="5" />
            </Form.Item>
            <Form.Item name="smstome_sync_max_pages_per_country" label="每国同步页数">
              <Input placeholder="5" />
            </Form.Item>
          </Card>
        )}

        {captchaSolver === 'yescaptcha' && (
          <Card title="验证码配置" style={{ marginBottom: 16 }}>
            <Form.Item name="yescaptcha_key" label="YesCaptcha Key">
              <Input />
            </Form.Item>
          </Card>
        )}

        {captchaSolver === 'local_solver' && (
          <Card title="本地 Solver 配置" style={{ marginBottom: 16 }}>
            <Form.Item name="solver_url" label="Solver URL">
              <Input />
            </Form.Item>
            <Text type="secondary" style={{ fontSize: 12 }}>
              启动命令: python services/turnstile_solver/start.py --browser_type camoufox --port 8889
            </Text>
          </Card>
        )}

        <Button type="primary" htmlType="submit" block disabled={polling} icon={polling ? <LoadingOutlined /> : <PlayCircleOutlined />}>
          {polling ? '注册中...' : '开始注册'}
        </Button>
      </Form>

      {task && (
        <Card title={
          <Space>
            <span>任务状态</span>
            <Tag color={
              task.status === 'done' ? 'success' :
              task.status === 'stopped' ? 'warning' :
              task.status === 'failed' ? 'error' : 'processing'
            }>
              {task.status}
            </Tag>
          </Space>
        } style={{ marginTop: 16 }}>
          <Descriptions column={1} size="small">
            <Descriptions.Item label="任务 ID">
              <Text copyable style={{ fontFamily: 'monospace' }}>{task.id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="进度">{task.progress}</Descriptions.Item>
            <Descriptions.Item label="跳过">{task.skipped ?? 0}</Descriptions.Item>
          </Descriptions>
          {task.success != null && (
            <div style={{ marginTop: 8, color: '#10b981' }}>
              <CheckCircleOutlined /> 成功 {task.success} 个
            </div>
          )}
          {task.errors?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              {task.errors.map((e: string, i: number) => (
                <div key={i} style={{ color: '#ef4444', marginBottom: 4 }}>
                  <CloseCircleOutlined /> {e}
                </div>
              ))}
            </div>
          )}
          {task.error && (
            <div style={{ marginTop: 8, color: '#ef4444' }}>
              <CloseCircleOutlined /> {task.error}
            </div>
          )}
          {task.id ? (
            <div style={{ marginTop: 16 }}>
              <TaskLogPanel taskId={task.id} />
            </div>
          ) : null}
        </Card>
      )}

      {(platform === 'chatgpt' || platform === 'codex') && cpaOutput ? (
        <Card title="CPA 快速检查输出" style={{ marginTop: 16 }}>
          <Input.TextArea value={cpaOutput} rows={12} readOnly style={{ fontFamily: 'monospace' }} />
        </Card>
      ) : null}
    </div>
  )
}
