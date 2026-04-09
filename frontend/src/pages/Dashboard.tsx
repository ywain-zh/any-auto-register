import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Progress, Tag, Button, Spin, Space, Typography } from 'antd'
import {
  UserOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  RiseOutlined,
} from '@ant-design/icons'
import { apiFetch } from '@/lib/utils'

const { Text } = Typography

const PLATFORM_COLORS: Record<string, string> = {
  trae: '#22d3ee',
  cursor: '#34d399',
}

const STATUS_COLORS: Record<string, string> = {
  registered: 'default',
  trial: 'success',
  subscribed: 'success',
  expired: 'warning',
  invalid: 'error',
}

export default function Dashboard() {
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const data = await apiFetch('/accounts/stats')
      setStats(data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const statCards = [
    {
      title: '总账号数',
      value: stats?.total ?? 0,
      icon: <UserOutlined style={{ fontSize: 24 }} />,
      color: '#22d3ee',
      hint: '当前库中的全部账号数量',
    },
    {
      title: '试用中',
      value: stats?.by_status?.trial ?? 0,
      icon: <ClockCircleOutlined style={{ fontSize: 24 }} />,
      color: '#f59e0b',
      hint: '处于试用有效期内的账号',
    },
    {
      title: '已订阅',
      value: stats?.by_status?.subscribed ?? 0,
      icon: <CheckCircleOutlined style={{ fontSize: 24 }} />,
      color: '#34d399',
      hint: '已升级为订阅状态的账号',
    },
    {
      title: '已失效',
      value: (stats?.by_status?.expired ?? 0) + (stats?.by_status?.invalid ?? 0),
      icon: <CloseCircleOutlined style={{ fontSize: 24 }} />,
      color: '#f87171',
      hint: '过期或探测失效的账号',
    },
  ]

  return (
    <div className="page-shell page-enter">
      <section className="page-hero">
        <div className="page-hero__eyebrow">
          <RiseOutlined />
          Dashboard overview
        </div>
        <h1 className="page-hero__title">仪表盘</h1>
        <p className="page-hero__description">
          统一查看账号总量、状态分布和平台占比。保留现有业务数据，只提升页面层次、卡片质感和控制台风格。
        </p>
      </section>

      <div className="page-toolbar">
        <div className="page-toolbar__group">
          <span className="muted-pill">总览已同步</span>
          <span className="muted-pill">数据源 /api/accounts/stats</span>
        </div>
        <Button icon={<ReloadOutlined spin={loading} />} onClick={load} loading={loading} type="primary">
          刷新数据
        </Button>
      </div>

      <Row gutter={[18, 18]}>
        {statCards.map(({ title, value, icon, color, hint }) => (
          <Col xs={24} sm={12} xl={6} key={title}>
            <Card className="glass-panel surface-card metric-card hover-lift" bordered={false}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                  <Statistic title={title} value={value} />
                  <Text type="secondary" style={{ fontSize: 12, lineHeight: 1.7 }}>
                    {hint}
                  </Text>
                </div>
                <div className="metric-card__icon" style={{ color }}>
                  {icon}
                </div>
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[18, 18]}>
        <Col xs={24} xl={12}>
          <Card title="平台分布" className="glass-panel section-card surface-card" bordered={false}>
            {loading ? (
              <div style={{ textAlign: 'center', padding: 56 }}>
                <Spin />
              </div>
            ) : stats ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                {Object.entries(stats.by_platform || {}).map(([platform, count]: any) => (
                  <div key={platform} className="detail-section" style={{ marginTop: 0 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10, gap: 12, alignItems: 'center' }}>
                      <Space size={8}>
                        <Tag color={PLATFORM_COLORS[platform] || 'default'}>{platform}</Tag>
                        <Text type="secondary">占比 {stats.total ? Math.round((count / stats.total) * 100) : 0}%</Text>
                      </Space>
                      <Text strong>{count}</Text>
                    </div>
                    <Progress
                      percent={stats.total ? Math.round((count / stats.total) * 100) : 0}
                      strokeColor={PLATFORM_COLORS[platform] || '#14b8a6'}
                      trailColor="rgba(148, 163, 184, 0.16)"
                      showInfo={false}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 56 }} className="subtle-text">
                暂无平台统计数据
              </div>
            )}
          </Card>
        </Col>

        <Col xs={24} xl={12}>
          <Card title="状态分布" className="glass-panel section-card surface-card" bordered={false}>
            {loading ? (
              <div style={{ textAlign: 'center', padding: 56 }}>
                <Spin />
              </div>
            ) : stats ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {Object.entries(stats.by_status || {}).map(([status, count]: any) => (
                  <div
                    key={status}
                    className="detail-section"
                    style={{
                      marginTop: 0,
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: 12,
                    }}
                  >
                    <Space size={10}>
                      <Tag color={STATUS_COLORS[status] || 'default'}>{status}</Tag>
                      <Text type="secondary">状态账号数</Text>
                    </Space>
                    <Text strong>{count}</Text>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 56 }} className="subtle-text">
                暂无状态统计数据
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
