import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Input, Row, Space, Statistic, Tag, Typography, message } from 'antd'
import { apiFetch } from '@/lib/utils'

const { Paragraph, Text } = Typography

type MonitorStatus = {
  configured: boolean
  base_url: string
  has_api_key?: boolean
  has_management_key?: boolean
  latest_report?: { path: string; content: any } | null
}

type RunState = 'idle' | 'running' | 'success' | 'error'

const SUMMARY_CANDIDATES = [
  { title: '总账号', keys: ['检查总数', 'total', 'total_accounts', 'account_total', 'total_count'], color: '#60a5fa' },
  { title: '可用账号', keys: ['可用账号', 'available', 'available_accounts', 'success', 'success_count'], color: '#34d399' },
  { title: '配额耗尽', keys: ['配额耗尽', 'quota_exhausted', 'quota_exceeded', 'insufficient_quota'], color: '#f59e0b' },
  { title: '401账号', keys: ['401账号', 'account_401', 'unauthorized_401', 'unauthorized'], color: '#ef4444' },
  { title: '异常', keys: ['异常', 'abnormal', 'failed_abnormal', 'error_accounts'], color: '#fb7185' },
  { title: '已禁用', keys: ['已禁用', 'disabled', 'disabled_accounts', 'paused'], color: '#f87171' },
  { title: '不可用', keys: ['不可用', 'unavailable', 'invalid', 'failed_other', 'failed_count_other'], color: '#fb7185' },
  { title: '待处理', keys: ['待处理', 'pending', 'pending_accounts', 'pending_count'], color: '#a78bfa' },
]

function readMetric(source: Record<string, any>, keys: string[]) {
  for (const key of keys) {
    const value = source?.[key]
    if (typeof value === 'number' || typeof value === 'string') {
      return value
    }
  }
  return 0
}

export default function Sub2ApiMonitor() {
  const [status, setStatus] = useState<MonitorStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [runState, setRunState] = useState<RunState>('idle')
  const [runError, setRunError] = useState('')

  const loadStatus = async () => {
    const data = await apiFetch('/sub2api-monitor/status')
    setStatus(data)
  }

  useEffect(() => {
    loadStatus().catch(() => {})
  }, [])

  const runCheck = async () => {
    setLoading(true)
    setRunState('running')
    setRunError('')
    try {
      const data = await apiFetch('/sub2api-monitor/run', {
        method: 'POST',
        body: JSON.stringify({
          page_size: 100,
          max_pages: 20,
          enable_remote_test: true,
          stop_on_error: false,
        }),
      })
      setResult(data)
      setRunState('success')
      message.success('Sub2API 监控执行完成')
      await loadStatus()
    } catch (e: any) {
      const errorText = String(e?.message || 'Sub2API 监控执行失败')
      setRunState('error')
      setRunError(errorText)
      message.error(errorText)
    } finally {
      setLoading(false)
    }
  }

  const reportContent = result?.latest_report?.content ?? status?.latest_report?.content ?? {}
  const counts = reportContent?.counts || reportContent?.summary || reportContent?.stats || {}
  const summaryItems = useMemo(() => (
    SUMMARY_CANDIDATES.map((item) => ({
      title: item.title,
      value: readMetric(counts, item.keys),
      color: item.color,
    }))
  ), [counts])

  const hasApiKey = status?.has_api_key ?? status?.has_management_key ?? false
  const outputText = [result?.stdout, result?.stderr, result?.output, result?.message].filter(Boolean).join('\n')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 'bold', margin: 0 }}>Sub2API 监控台</h1>
        <p style={{ color: '#7a8ba3', marginTop: 4 }}>查看 Sub2API 连接状态、运行监控脚本，并展示最新检测报告。</p>
      </div>

      <Card
        title="关键指标"
        extra={
          <Space>
            {status?.configured ? <Tag color="green">Sub2API 已连接</Tag> : <Tag color="red">Sub2API 未配置</Tag>}
            {status?.latest_report?.path ? <Tag>{status.latest_report.path}</Tag> : null}
          </Space>
        }
      >
        {!status?.latest_report?.content && !result?.latest_report?.content ? (
          <div style={{ marginBottom: 16, color: '#7a8ba3' }}>还没有检测报告，先运行一次脚本后这里会展示 Sub2API 关键数据。</div>
        ) : null}
        <Row gutter={[16, 16]}>
          {summaryItems.map((item) => (
            <Col key={item.title} xs={12} md={8} xl={4}>
              <Card size="small" styles={{ body: { padding: 16 } }}>
                <Statistic title={item.title} value={Number(item.value || 0)} valueStyle={{ color: item.color, fontWeight: 700 }} />
              </Card>
            </Col>
          ))}
        </Row>
        <div style={{ marginTop: 12, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <Text type="secondary">Base URL: {status?.base_url || '-'}</Text>
          <Text type="secondary">API Key: {hasApiKey ? '已配置' : '未配置'}</Text>
        </div>
      </Card>

      <Card
        title="运行检查"
        extra={
          <Space>
            {runState === 'running' ? <Tag color="processing">执行中</Tag> : null}
            {runState === 'success' ? <Tag color="success">最近一次执行成功</Tag> : null}
            {runState === 'error' ? <Tag color="error">最近一次执行失败</Tag> : null}
            <Button type="primary" loading={loading} onClick={runCheck}>运行脚本</Button>
          </Space>
        }
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Text type="secondary">调用 `/api/sub2api-monitor/run` 执行最新监控任务，执行完成后会自动刷新状态和报告。</Text>
          {runState === 'running' ? <Text type="warning">脚本正在执行，请稍候，完成后会自动刷新报告。</Text> : null}
          {runState === 'success' ? <Text type="success">脚本已执行完成，结果已刷新。</Text> : null}
          {runError ? <Alert type="error" showIcon message="Sub2API 监控执行失败" description={runError} /> : null}
        </Space>
      </Card>

      <Card title="运行输出">
        <Input.TextArea
          value={outputText}
          rows={18}
          readOnly
          style={{ fontFamily: 'monospace' }}
          placeholder={loading ? '脚本正在执行中，完成后将在这里显示 stdout / stderr。' : '运行后将在这里显示 stdout / stderr。'}
        />
      </Card>

      <Card title="最新报告 JSON">
        <Paragraph copyable style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', marginBottom: 0 }}>
          {JSON.stringify(reportContent, null, 2)}
        </Paragraph>
      </Card>
    </div>
  )
}
