import { useEffect, useState } from 'react'
import { Button, Card, Checkbox, Col, Input, Row, Space, Statistic, Tag, Typography } from 'antd'
import { apiFetch } from '@/lib/utils'

const { Paragraph, Text } = Typography

type MonitorStatus = {
  configured: boolean
  base_url: string
  has_management_key: boolean
  latest_report?: { path: string; content: any } | null
}

export default function CpaMonitor() {
  const [status, setStatus] = useState<MonitorStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [dryRun, setDryRun] = useState(false)
  const [enableApiCallCheck, setEnableApiCallCheck] = useState(false)
  const [enableDisabledRecovery, setEnableDisabledRecovery] = useState(true)
  const [result, setResult] = useState<any>(null)

  const loadStatus = async () => {
    const data = await apiFetch('/cpa-monitor/status')
    setStatus(data)
  }

  useEffect(() => {
    loadStatus().catch(() => {})
  }, [])

  const runCheck = async () => {
    setLoading(true)
    try {
      const data = await apiFetch('/cpa-monitor/run', {
        method: 'POST',
        body: JSON.stringify({
          dry_run: dryRun,
          once: true,
          enable_api_call_check: enableApiCallCheck,
          enable_disabled_recovery: enableDisabledRecovery,
        }),
      })
      setResult(data)
      await loadStatus()
    } finally {
      setLoading(false)
    }
  }

  const reportContent = result?.latest_report?.content ?? status?.latest_report?.content ?? {}
  const counts = reportContent?.counts || reportContent?.summary || {}
  const summaryItems = [
    { title: '总账号', value: counts['检查总数'] ?? counts['total'] ?? 0, color: '#60a5fa' },
    { title: '可用账号', value: counts['可用账号'] ?? counts['available'] ?? 0, color: '#34d399' },
    { title: '配额耗尽', value: counts['配额耗尽'] ?? counts['quota_exhausted'] ?? 0, color: '#f59e0b' },
    { title: '已禁用', value: counts['已禁用'] ?? counts['disabled'] ?? 0, color: '#f87171' },
    { title: '不可用', value: counts['不可用'] ?? counts['unavailable'] ?? 0, color: '#fb7185' },
    { title: '待删401', value: counts['待删除401'] ?? counts['delete_401'] ?? 0, color: '#ef4444' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <h1 style={{ fontSize: 24, fontWeight: 'bold', margin: 0 }}>CPA 监控台</h1>
        <p style={{ color: '#7a8ba3', marginTop: 4 }}>运行 `check.js` 检测并清理 CLIProxyAPI / CPA 账号状态</p>
      </div>

      <Card
        title="关键指标"
        extra={
          <Space>
            {status?.configured ? <Tag color="green">CPA 已连接</Tag> : <Tag color="red">CPA 未配置</Tag>}
            {status?.latest_report?.path ? <Tag>{status.latest_report.path}</Tag> : null}
          </Space>
        }
      >
        {!status?.latest_report?.content && !result?.latest_report?.content ? (
          <div style={{ marginBottom: 16, color: '#7a8ba3' }}>还没有检测报告，先运行一次脚本后这里会展示 CPA 关键数据。</div>
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
          <Text type="secondary">Management Key: {status?.has_management_key ? '已配置' : '未配置'}</Text>
        </div>
      </Card>

      <Card title="运行检查" extra={<Button type="primary" loading={loading} onClick={runCheck}>运行脚本</Button>}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Checkbox checked={dryRun} onChange={(e) => setDryRun(e.target.checked)}>Dry Run（只检查，不执行删除/禁用）</Checkbox>
          <Checkbox checked={enableApiCallCheck} onChange={(e) => setEnableApiCallCheck(e.target.checked)}>启用 /api-call 主动探测</Checkbox>
          <Checkbox checked={enableDisabledRecovery} onChange={(e) => setEnableDisabledRecovery(e.target.checked)}>启用 disabled 账号恢复探测</Checkbox>
          <Text type="secondary">脚本会读取全局配置中的 `CLIProxyAPI / CPA` 地址和管理口令。</Text>
        </Space>
      </Card>

      <Card title="运行输出">
        <Input.TextArea value={[result?.stdout, result?.stderr].filter(Boolean).join('\n')} rows={18} readOnly style={{ fontFamily: 'monospace' }} />
      </Card>

      <Card title="最新报告 JSON">
        <Paragraph copyable style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', marginBottom: 0 }}>
          {JSON.stringify(result?.latest_report?.content ?? status?.latest_report?.content ?? {}, null, 2)}
        </Paragraph>
      </Card>
    </div>
  )
}
