import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Col, Input, Row, Space, Statistic, Tag, Typography } from 'antd'
import { apiFetch } from '@/lib/utils'

const { Paragraph, Text } = Typography

type MonitorStatus = {
  configured: boolean
  base_url: string
  has_api_key?: boolean
  has_management_key?: boolean
  latest_report?: { path: string; content: any } | null
}

const SUMMARY_CANDIDATES = [
  { title: '总账号', keys: ['检查总数', 'total', 'total_accounts', 'account_total', 'total_count'], color: '#60a5fa' },
  { title: '可用账号', keys: ['可用账号', 'available', 'available_accounts', 'success', 'success_count'], color: '#34d399' },
  { title: '配额耗尽', keys: ['配额耗尽', 'quota_exhausted', 'quota_exceeded', 'insufficient_quota'], color: '#f59e0b' },
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

  const loadStatus = async () => {
    const data = await apiFetch('/sub2api-monitor/status')
    setStatus(data)
  }

  useEffect(() => {
    loadStatus().catch(() => {})
  }, [])

  const runCheck = async () => {
    setLoading(true)
    try {
      const data = await apiFetch('/sub2api-monitor/run', {
        method: 'POST',
      })
      setResult(data)
      await loadStatus()
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

      <Card title="运行检查" extra={<Button type="primary" loading={loading} onClick={runCheck}>运行脚本</Button>}>
        <Text type="secondary">调用 `/api/sub2api-monitor/run` 执行最新监控任务，执行完成后会自动刷新状态和报告。</Text>
      </Card>

      <Card title="运行输出">
        <Input.TextArea value={outputText} rows={18} readOnly style={{ fontFamily: 'monospace' }} placeholder="运行后将在这里显示 stdout / stderr。" />
      </Card>

      <Card title="最新报告 JSON">
        <Paragraph copyable style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', marginBottom: 0 }}>
          {JSON.stringify(reportContent, null, 2)}
        </Paragraph>
      </Card>
    </div>
  )
}
