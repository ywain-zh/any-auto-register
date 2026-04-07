import { useEffect, useMemo, useState } from 'react'
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { apiFetch } from '@/lib/utils'
import { getProviderFormInitialValues, normalizeProviderConfig, ProviderConfigFields } from '@/pages/mailboxes/providerConfig'
import type { MailboxProviderMeta } from '@/pages/mailboxes/providerConfig'

const { Text } = Typography

type MailboxService = {
  id: number
  name: string
  provider: string
  config: Record<string, any>
  is_active: boolean
  created_at: string
  updated_at: string
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function maskValue(value: unknown, secret = false) {
  const text = String(value ?? '').trim()
  if (!text) return '-'
  if (secret) {
    if (text.length <= 8) return '******'
    return `${text.slice(0, 3)}***${text.slice(-3)}`
  }
  if (text.length > 60) return `${text.slice(0, 57)}...`
  return text
}

function safeParseArray(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item || '')).filter(Boolean)
  if (typeof value !== 'string') return []
  const text = value.trim()
  if (!text) return []
  try {
    const parsed = JSON.parse(text)
    return Array.isArray(parsed) ? parsed.map((item) => String(item || '')).filter(Boolean) : []
  } catch {
    return []
  }
}

function summarizeConfig(provider: MailboxProviderMeta | null | undefined, config: Record<string, any>) {
  if (!provider) return '-'
  if (provider.key === 'cfworker') {
    const domains = safeParseArray(config.cfworker_domains)
    const enabled = safeParseArray(config.cfworker_enabled_domains)
    const parts = [
      config.cfworker_api_url ? `API: ${maskValue(config.cfworker_api_url)}` : '',
      domains.length ? `域名池: ${domains.length}` : config.cfworker_domain ? `单域名: ${config.cfworker_domain}` : '',
      enabled.length ? `启用: ${enabled.length}` : '',
    ].filter(Boolean)
    return parts.join(' | ') || '-'
  }

  const parts = provider.fields
    .slice(0, 3)
    .map((field) => {
      const value = config?.[field.key]
      if (value === undefined || value === null || value === '') return ''
      if (typeof value === 'boolean') return `${field.label}: ${value ? '开启' : '关闭'}`
      return `${field.label}: ${maskValue(value, field.secret)}`
    })
    .filter(Boolean)

  return parts.join(' | ') || '已配置'
}

export default function MailboxProviders() {
  const [providers, setProviders] = useState<MailboxProviderMeta[]>([])
  const [services, setServices] = useState<MailboxService[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [editingService, setEditingService] = useState<MailboxService | null>(null)
  const [providerKey, setProviderKey] = useState('')

  const [form] = Form.useForm()

  const providerMap = useMemo(
    () => Object.fromEntries(providers.map((provider) => [provider.key, provider])),
    [providers],
  )
  const providerOptions = providers.map((provider) => ({ label: provider.label, value: provider.key }))
  const currentProvider = providerKey ? providerMap[providerKey] : null
  const activeCount = services.filter((item) => item.is_active).length

  const loadData = async () => {
    setLoading(true)
    try {
      const [providerData, serviceData] = await Promise.all([
        apiFetch('/mailboxes/providers'),
        apiFetch('/mailboxes'),
      ])
      setProviders(Array.isArray(providerData) ? providerData : [])
      setServices(Array.isArray(serviceData) ? serviceData : [])
    } catch (e: any) {
      message.error(`加载邮箱服务失败: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const resetModal = () => {
    setModalOpen(false)
    setEditingService(null)
    setProviderKey('')
    form.resetFields()
  }

  const openCreateModal = () => {
    setEditingService(null)
    setProviderKey('')
    form.resetFields()
    setModalOpen(true)
  }

  const openEditModal = (record: MailboxService) => {
    const provider = providerMap[record.provider]
    setEditingService(record)
    setProviderKey(record.provider)
    form.resetFields()
    form.setFieldsValue({
      name: record.name,
      provider: record.provider,
      ...getProviderFormInitialValues(provider, record.config || {}),
    })
    setModalOpen(true)
  }

  const handleProviderChange = (nextProviderKey: string) => {
    const provider = providerMap[nextProviderKey]
    const currentName = form.getFieldValue('name')
    form.resetFields()
    setProviderKey(nextProviderKey)
    form.setFieldsValue({
      name: currentName,
      provider: nextProviderKey,
      ...getProviderFormInitialValues(provider),
    })
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      const provider = providerMap[values.provider]
      if (!provider) {
        message.error('请选择邮箱 Provider')
        return
      }

      const { config, domains, enabledDomains } = normalizeProviderConfig(provider, values)
      if (provider.key === 'cfworker' && domains.length > 0 && enabledDomains.length === 0) {
        message.error('CF Worker 至少需要启用一个域名')
        return
      }

      setSubmitting(true)
      const payload = {
        name: values.name,
        provider: provider.key,
        config,
      }

      if (editingService) {
        await apiFetch(`/mailboxes/${editingService.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            ...payload,
            is_active: editingService.is_active,
          }),
        })
        message.success('邮箱服务已更新')
      } else {
        await apiFetch('/mailboxes', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
        message.success('邮箱服务已创建')
      }

      resetModal()
      await loadData()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(`保存邮箱服务失败: ${e.message}`)
    } finally {
      setSubmitting(false)
    }
  }

  const handleToggle = async (record: MailboxService) => {
    try {
      await apiFetch(`/mailboxes/${record.id}/toggle`, { method: 'PATCH' })
      message.success(record.is_active ? '已停用邮箱服务' : '已启用邮箱服务')
      await loadData()
    } catch (e: any) {
      message.error(`切换状态失败: ${e.message}`)
    }
  }

  const handleDelete = async (record: MailboxService) => {
    try {
      await apiFetch(`/mailboxes/${record.id}`, { method: 'DELETE' })
      message.success('邮箱服务已删除')
      await loadData()
    } catch (e: any) {
      message.error(`删除邮箱服务失败: ${e.message}`)
    }
  }

  const columns: any[] = [
    {
      title: '服务名',
      dataIndex: 'name',
      key: 'name',
      render: (value: string) => <span style={{ fontWeight: 600 }}>{value}</span>,
    },
    {
      title: 'Provider',
      dataIndex: 'provider',
      key: 'provider',
      render: (value: string) => <Tag color="blue">{providerMap[value]?.label || value}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (value: boolean) => <Tag color={value ? 'success' : 'default'}>{value ? '启用' : '停用'}</Tag>,
    },
    {
      title: '配置摘要',
      dataIndex: 'config',
      key: 'config',
      ellipsis: true,
      render: (value: Record<string, any>, record: MailboxService) => summarizeConfig(providerMap[record.provider], value || {}),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_: any, record: MailboxService) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEditModal(record)} />
          <Button size="small" onClick={() => handleToggle(record)}>
            {record.is_active ? '停用' : '启用'}
          </Button>
          <Popconfirm title="确认删除该邮箱服务？" onConfirm={() => handleDelete(record)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 'bold', margin: 0 }}>邮箱服务管理</h1>
          <p style={{ color: '#7a8ba3', marginTop: 4 }}>列表化维护系统已接入的邮箱 Provider 服务实例。</p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined spin={loading} />} onClick={loadData}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
            添加服务
          </Button>
        </Space>
      </div>

      <Card title={`Provider 服务 (${services.length})`} extra={<Text type="secondary">已启用 {activeCount} 个</Text>}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={services}
          loading={loading}
          pagination={false}
          locale={{ emptyText: <Empty description="还没有配置邮箱 Provider 服务，请先添加。" /> }}
          scroll={{ x: 980 }}
        />
      </Card>

      <Modal
        title={editingService ? '编辑邮箱服务' : '添加邮箱服务'}
        open={modalOpen}
        onCancel={resetModal}
        onOk={handleSubmit}
        confirmLoading={submitting}
        width={760}
        maskClosable={false}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="服务名称" rules={[{ required: true, message: '请输入服务名称' }]}>
            <Input placeholder="例如：GPTMail 主池 / CFWorker 备用池" />
          </Form.Item>
          <Form.Item name="provider" label="Provider" rules={[{ required: true, message: '请选择 Provider' }]}>
            <Select
              placeholder="请选择 Provider"
              options={providerOptions}
              onChange={handleProviderChange}
              disabled={!!editingService}
            />
          </Form.Item>
          <ProviderConfigFields provider={currentProvider} />
        </Form>
      </Modal>
    </div>
  )
}
