import { BrowserRouter, Navigate, Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { App as AntdApp, ConfigProvider, Layout, Menu, Button, Spin, Typography, Space } from 'antd'
import {
  DashboardOutlined,
  UserOutlined,
  GlobalOutlined,
  HistoryOutlined,
  SettingOutlined,
  SunOutlined,
  MoonOutlined,
  LogoutOutlined,
  MailOutlined,
} from '@ant-design/icons'
import zhCN from 'antd/locale/zh_CN'
import Dashboard from '@/pages/Dashboard'
import Accounts from '@/pages/Accounts'
import RegisterTaskPage from '@/pages/RegisterTaskPage'
import Proxies from '@/pages/Proxies'
import Settings from '@/pages/Settings'
import TaskHistory from '@/pages/TaskHistory'
import Login from '@/pages/Login'
import CpaMonitor from '@/pages/CpaMonitor'
import Sub2ApiMonitor from '@/pages/Sub2ApiMonitor'
import Mailboxes from '@/pages/Mailboxes'
import MailboxProviders from '@/pages/MailboxProviders'
import { darkTheme, lightTheme } from './theme'
import { apiFetch, clearToken, getToken } from '@/lib/utils'

const { Sider, Content } = Layout
const { Text } = Typography

function ProtectedLayout() {
  const navigate = useNavigate()
  const [ready, setReady] = useState(false)

  useEffect(() => {
    fetch('/api/auth/status')
      .then(r => r.json())
      .then(s => {
        const token = getToken()
        if (s.has_password && !token) {
          navigate('/login', { replace: true })
        } else {
          setReady(true)
        }
      })
      .catch(() => setReady(true))
  }, [])

  if (!ready) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }

  return <AppContent />
}

function AppContent() {
  const [themeMode, setThemeMode] = useState<'dark' | 'light'>(() =>
    (localStorage.getItem('theme') as 'dark' | 'light') || 'dark'
  )
  const [collapsed, setCollapsed] = useState(false)
  const [platforms, setPlatforms] = useState<{ key: string; label: string }[]>([])
  const [hasPassword, setHasPassword] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    document.documentElement.classList.toggle('light', themeMode === 'light')
    document.documentElement.style.setProperty(
      '--sider-trigger-border',
      themeMode === 'light' ? 'rgba(0,0,0,0.1)' : 'rgba(255,255,255,0.15)'
    )
    localStorage.setItem('theme', themeMode)
  }, [themeMode])

  useEffect(() => {
    fetch('/api/auth/status').then(r => r.json()).then(s => setHasPassword(s.has_password)).catch(() => {})
  }, [])

  useEffect(() => {
    apiFetch('/platforms')
      .then(d => setPlatforms((d || [])
        .filter((p: any) => !['tavily', 'cursor'].includes(p.name))
        .map((p: any) => ({ key: p.name, label: p.display_name }))))
      .catch(() => {})
  }, [])

  const isLight = themeMode === 'light'
  const currentTheme = isLight ? lightTheme : darkTheme

  const getSelectedKey = () => {
    const path = location.pathname
    if (path === '/') return ['/']
    if (path.startsWith('/accounts')) return [path]
    if (path.startsWith('/mailboxes/providers')) return ['/mailboxes/providers']
    if (path.startsWith('/mailboxes')) return ['/mailboxes/inboxes']
    if (path === '/history') return ['/history']
    if (path === '/cpa-monitor') return ['/cpa-monitor']
    if (path === '/sub2api-monitor') return ['/sub2api-monitor']
    if (path === '/proxies') return ['/proxies']
    if (path === '/settings') return ['/settings']
    return ['/']
  }

  const menuItems = [
    {
      key: '/',
      icon: <DashboardOutlined />,
      label: '仪表盘',
    },
    {
      key: '/accounts',
      icon: <UserOutlined />,
      label: '平台管理',
      children: platforms.map(p => ({
        key: `/accounts/${p.key}`,
        label: p.label,
      })),
    },
    {
      key: '/mailboxes',
      icon: <MailOutlined />,
      label: '邮箱服务',
      children: [
        {
          key: '/mailboxes/inboxes',
          label: '微软邮箱',
        },
        {
          key: '/mailboxes/providers',
          label: '邮箱服务管理',
        },
      ],
    },
    {
      key: '/history',
      icon: <HistoryOutlined />,
      label: '任务历史',
    },
    {
      key: '/cpa-monitor',
      icon: <DashboardOutlined />,
      label: 'CPA 监控台',
    },
    {
      key: '/sub2api-monitor',
      icon: <DashboardOutlined />,
      label: 'Sub2API 监控台',
    },
    {
      key: '/proxies',
      icon: <GlobalOutlined />,
      label: '代理管理',
    },
    {
      key: '/settings',
      icon: <SettingOutlined />,
      label: '全局配置',
    },
  ]

  return (
    <ConfigProvider theme={currentTheme} locale={zhCN}>
      <AntdApp>
        <Layout className="app-shell">
          <Sider
            collapsible
            collapsed={collapsed}
            onCollapse={setCollapsed}
            className="app-shell__sider"
            style={{
              background: currentTheme.token?.colorBgContainer,
              borderRight: `1px solid ${currentTheme.token?.colorBorder}`,
            }}
            width={284}
            collapsedWidth={96}
          >
            <div className="app-shell__brand">
              <div className="app-shell__brand-mark">
                <DashboardOutlined />
              </div>
              {!collapsed && (
                <div className="app-shell__brand-copy">
                  <div className="app-shell__brand-title">Any Auto Register</div>
                  <div className="app-shell__brand-subtitle">Teal dashboard workspace</div>
                </div>
              )}
            </div>
            <div className="app-shell__sider-body">
              <Menu
                mode="inline"
                selectedKeys={getSelectedKey()}
                defaultOpenKeys={['/accounts']}
                items={menuItems}
                onClick={({ key }) => navigate(key)}
                className="app-shell__menu"
              />
              <div className="app-shell__footer">
                {!collapsed && (
                  <Space direction="vertical" size={4}>
                    <Text style={{ color: currentTheme.token?.colorText, fontWeight: 600 }}>Workspace</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      统一管理注册、邮箱、监控与代理任务
                    </Text>
                  </Space>
                )}
                <Button
                  block
                  icon={isLight ? <SunOutlined /> : <MoonOutlined />}
                  onClick={() => setThemeMode(isLight ? 'dark' : 'light')}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: collapsed ? 'center' : 'space-between',
                    height: 42,
                  }}
                >
                  {!collapsed && (isLight ? '亮色模式' : '暗色模式')}
                </Button>
                {hasPassword && (
                  <Button
                    block
                    danger
                    icon={<LogoutOutlined />}
                    onClick={() => { clearToken(); navigate('/login') }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: collapsed ? 'center' : 'space-between',
                      height: 42,
                    }}
                  >
                    {!collapsed && '退出登录'}
                  </Button>
                )}
              </div>
            </div>
          </Sider>
          <Content className="app-shell__content">
            <div className="app-shell__content-inner">
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/accounts" element={<Accounts />} />
                <Route path="/accounts/:platform" element={<Accounts />} />
                <Route path="/mailboxes" element={<Navigate to="/mailboxes/inboxes" replace />} />
                <Route path="/mailboxes/inboxes" element={<Mailboxes />} />
                <Route path="/mailboxes/providers" element={<MailboxProviders />} />
                <Route path="/register" element={<RegisterTaskPage />} />
                <Route path="/history" element={<TaskHistory />} />
                <Route path="/cpa-monitor" element={<CpaMonitor />} />
                <Route path="/sub2api-monitor" element={<Sub2ApiMonitor />} />
                <Route path="/proxies" element={<Proxies />} />
                <Route path="/settings" element={<Settings />} />
              </Routes>
            </div>
          </Content>
        </Layout>
      </AntdApp>
    </ConfigProvider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/*" element={<ProtectedLayout />} />
      </Routes>
    </BrowserRouter>
  )
}
