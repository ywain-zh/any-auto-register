import { useEffect, useMemo, useState } from 'react'
import {
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  MailOutlined,
  ReloadOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { apiFetch } from '@/lib/utils'

const { Text, Paragraph } = Typography

const HOTMAIL_PROVIDER = 'hotmail'

type MailboxService = {
  id: number
  name: string
  provider: string
  config: Record<string, any>
  is_active: boolean
  created_at: string
  updated_at: string
}

type HotmailAccount = {
  id: number
  mailbox_service_id: number
  email: string
  mailbox_password: string
  client_id: string
  refresh_token: string
  register_status: string
  claimed_at?: string | null
  last_error: string
  openai_password: string
  created_at: string
  updated_at: string
}

type HotmailMail = {
  message_id: string
  folder: string
  subject: string
  from: string
  received_at: string
  snippet: string
  body_text?: string
  body_html?: string
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function maskToken(value?: string) {
  const token = String(value || '')
  if (!token) return '-'
  if (token.length <= 18) return token
  return `${token.slice(0, 8)}...${token.slice(-8)}`
}

function getFolderTag(value: string) {
  const folder = String(value || '')
  if (folder === 'Junk') return <Tag color="warning">垃圾箱</Tag>
  if (folder === 'INBOX') return <Tag color="blue">收件箱</Tag>
  return <Tag>{folder || '-'}</Tag>
}

function getStatusTag(value: string) {
  const status = String(value || '')
  if (status === 'success') return <Tag color="success">成功</Tag>
  if (status === 'failed') return <Tag color="error">失败</Tag>
  if (status === 'pending_bind') return <Tag color="gold">待绑定</Tag>
  if (status === 'registered') return <Tag color="processing">已注册</Tag>
  return <Tag>{status || '未注册'}</Tag>
}

export default function Mailboxes() {
  const [services, setServices] = useState<MailboxService[]>([])
  const [servicesLoading, setServicesLoading] = useState(false)
  const [selectedServiceId, setSelectedServiceId] = useState<number | null>(null)
  const [accounts, setAccounts] = useState<HotmailAccount[]>([])
  const [accountsLoading, setAccountsLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [selectedAccount, setSelectedAccount] = useState<HotmailAccount | null>(null)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importLoading, setImportLoading] = useState(false)
  const [mailModalOpen, setMailModalOpen] = useState(false)
  const [mailLoading, setMailLoading] = useState(false)
  const [mails, setMails] = useState<HotmailMail[]>([])
  const [mailDetail, setMailDetail] = useState<HotmailMail | null>(null)

  const hotmailServices = useMemo(() => services.filter(item => item.provider === HOTMAIL_PROVIDER), [services])

  const selectedService = useMemo(
    () => hotmailServices.find(item => item.id === selectedServiceId) || null,
    [hotmailServices, selectedServiceId],
  )

  const activeServiceCount = hotmailServices.filter(item => item.is_active).length

  const loadServices = async (preferredId?: number | null) => {
    setServicesLoading(true)
    try {
      const data = await apiFetch('/mailboxes')
      const rows = Array.isArray(data) ? data : []
      setServices(rows)
      const hotmailRows = rows.filter((item: MailboxService) => item.provider === HOTMAIL_PROVIDER)
      if (!hotmailRows.length) {
        setSelectedServiceId(null)
        setAccounts([])
        setTotal(0)
        setSelectedAccount(null)
        return null
      }
      const nextId = preferredId ?? selectedServiceId
      const matched = nextId && hotmailRows.some((item: MailboxService) => item.id === nextId)
      const resolvedServiceId = matched ? Number(nextId) : hotmailRows[0].id
      setSelectedServiceId(resolvedServiceId)
      return resolvedServiceId
    } catch (e: any) {
      message.error(`加载邮箱服务失败: ${e.message}`)
      return null
    } finally {
      setServicesLoading(false)
    }
  }

  const loadAccounts = async (serviceId: number, nextPage = page, nextPageSize = pageSize) => {
    setAccountsLoading(true)
    try {
      const data = await apiFetch(`/mailboxes/${serviceId}/hotmail/accounts?page=${nextPage}&page_size=${nextPageSize}`)
      const rows = Array.isArray(data?.items) ? data.items : []
      setAccounts(rows)
      setTotal(Number(data?.total || 0))
      setPage(Number(data?.page || nextPage))
      setPageSize(Number(data?.page_size || nextPageSize))
      setSelectedAccount(current => rows.find((item: HotmailAccount) => item.id === current?.id) || rows[0] || null)
    } catch (e: any) {
      message.error(`加载微软邮箱账号失败: ${e.message}`)
    } finally {
      setAccountsLoading(false)
    }
  }

  const refreshCurrentView = async () => {
    const resolvedServiceId = await loadServices(selectedServiceId)
    if (resolvedServiceId) {
      await loadAccounts(resolvedServiceId, page, pageSize)
    }
  }

  useEffect(() => {
    refreshCurrentView()
  }, [])

  useEffect(() => {
    if (!selectedServiceId) return
    loadAccounts(selectedServiceId, 1, pageSize)
  }, [selectedServiceId])

  const loadImportFile = async (file: File) => {
    const text = await file.text()
    const nextText = text.trim()
    if (!nextText) {
      message.warning('TXT 文件内容为空')
      return
    }
    setImportText(nextText)
    message.success('TXT 内容已读取，请确认后导入')
  }

  const handleImport = async () => {
    if (!selectedServiceId) {
      message.warning('请先选择微软邮箱服务')
      return
    }
    const lines = importText.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
    if (!lines.length) {
      message.warning('请先粘贴或读取 TXT 内容')
      return
    }
    setImportLoading(true)
    try {
      const result = await apiFetch(`/mailboxes/${selectedServiceId}/hotmail/import`, {
        method: 'POST',
        body: JSON.stringify({ lines }),
      })
      message.success(`导入完成：新增 ${result.created}，更新 ${result.updated}，跳过 ${result.skipped}`)
      setImportModalOpen(false)
      setImportText('')
      await loadAccounts(selectedServiceId, 1, pageSize)
    } catch (e: any) {
      message.error(`导入失败: ${e.message}`)
    } finally {
      setImportLoading(false)
    }
  }

  const handleOpenMails = async (record?: HotmailAccount | null) => {
    const target = record || selectedAccount
    if (!selectedServiceId || !target) {
      message.warning('请先选择微软邮箱账号')
      return
    }
    setSelectedAccount(target)
    setMailModalOpen(true)
    setMailDetail(null)
    setMailLoading(true)
    try {
      const result = await apiFetch(`/mailboxes/${selectedServiceId}/hotmail/accounts/${target.id}/mails`)
      setMails(Array.isArray(result?.items) ? result.items : [])
    } catch (e: any) {
      message.error(`查询邮件失败: ${e.message}`)
      setMails([])
    } finally {
      setMailLoading(false)
    }
  }

  const accountColumns: any[] = [
    {
      title: '邮箱',
      dataIndex: 'email',
      key: 'email',
      render: (value: string) => <span style={{ fontFamily: 'monospace' }}>{value}</span>,
    },
    {
      title: 'client_id',
      dataIndex: 'client_id',
      key: 'client_id',
      render: (value: string) => <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{value || '-'}</span>,
    },
    {
      title: 'refresh_token',
      dataIndex: 'refresh_token',
      key: 'refresh_token',
      render: (value: string) => <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{maskToken(value)}</span>,
    },
    {
      title: '状态',
      dataIndex: 'register_status',
      key: 'register_status',
      render: (value: string) => getStatusTag(value),
    },
    {
      title: '最近错误',
      dataIndex: 'last_error',
      key: 'last_error',
      ellipsis: true,
      render: (value: string) => value || '-',
    },
    {
      title: '导入时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: any, record: HotmailAccount) => (
        <Button size="small" icon={<MailOutlined />} onClick={() => handleOpenMails(record)}>
          查邮件
        </Button>
      ),
    },
  ]

  const mailColumns: any[] = [
    {
      title: '主题',
      dataIndex: 'subject',
      key: 'subject',
      render: (_: string, record: HotmailMail) => (
        <Button type="link" onClick={() => setMailDetail(record)} style={{ paddingInline: 0, textAlign: 'left', height: 'auto' }}>
          {record.subject || '(无主题)'}
        </Button>
      ),
    },
    {
      title: '发件人',
      dataIndex: 'from',
      key: 'from',
      render: (value: string) => value || '-',
    },
    {
      title: '文件夹',
      dataIndex: 'folder',
      key: 'folder',
      render: (value: string) => getFolderTag(value),
    },
    {
      title: '收件时间',
      dataIndex: 'received_at',
      key: 'received_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '摘要',
      dataIndex: 'snippet',
      key: 'snippet',
      ellipsis: true,
      render: (value: string) => value || '-',
    },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 'bold', margin: 0 }}>微软邮箱</h1>
          <p style={{ color: '#7a8ba3', marginTop: 4 }}>
            在这里统一管理 Hotmail / Microsoft 邮箱服务实例、账号导入和查邮件能力。
          </p>
        </div>
        <Space>
          <Button icon={<ReloadOutlined spin={servicesLoading || accountsLoading} />} onClick={refreshCurrentView}>
            刷新
          </Button>
          <Button onClick={() => setImportModalOpen(true)} disabled={!selectedService}>
            导入账号
          </Button>
        </Space>
      </div>

      <Card
        title={selectedService ? `微软邮箱账号 - ${selectedService.name}` : '微软邮箱账号'}
        extra={selectedService ? <Text type="secondary">共 {total} 个</Text> : null}
      >
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <Space wrap>
            <Text type="secondary">邮箱服务</Text>
            <Select
              value={selectedServiceId ?? undefined}
              style={{ minWidth: 240 }}
              placeholder="选择微软邮箱服务"
              options={hotmailServices.map((item) => ({
                value: item.id,
                label: item.name,
              }))}
              onChange={(value) => setSelectedServiceId(value)}
            />
            <Text type="secondary">已启用 {activeServiceCount} 个</Text>
          </Space>
        </div>
        {selectedService ? (
          <Table
            rowKey="id"
            columns={accountColumns}
            dataSource={accounts}
            loading={accountsLoading}
            size="middle"
            locale={{
              emptyText: '当前服务下还没有微软邮箱账号，请先导入 TXT 或粘贴内容。',
            }}
            rowSelection={{
              type: 'radio',
              selectedRowKeys: selectedAccount ? [selectedAccount.id] : [],
              onChange: (_keys, rows) => setSelectedAccount((rows?.[0] as HotmailAccount) || null),
            }}
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              pageSizeOptions: ['10', '20', '50', '100'],
              onChange: (nextPage, nextPageSize) => {
                if (!selectedServiceId) return
                loadAccounts(selectedServiceId, nextPage, nextPageSize)
              },
            }}
            scroll={{ x: 1120 }}
          />
        ) : (
          <Empty description="请先新增或选择一个微软邮箱服务" />
        )}
      </Card>

      <Modal
        title={selectedService ? `导入微软邮箱 - ${selectedService.name}` : '导入微软邮箱'}
        open={importModalOpen}
        onCancel={() => {
          setImportModalOpen(false)
          setImportText('')
        }}
        onOk={handleImport}
        confirmLoading={importLoading}
        maskClosable={false}
        width={760}
      >
        <Space style={{ marginBottom: 12 }} wrap>
          <Button
            icon={<UploadOutlined />}
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'
              input.accept = '.txt,text/plain'
              input.onchange = async () => {
                const file = input.files?.[0]
                if (file) await loadImportFile(file)
              }
              input.click()
            }}
          >
            读取 TXT
          </Button>
          <Text type="secondary">支持 TXT 导入，也支持直接粘贴多行账号内容。</Text>
        </Space>
        <Paragraph type="secondary" style={{ marginBottom: 8 }}>
          每行格式：
          <code style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 4px', borderRadius: 4 }}>
            邮箱----密码----client_id----refresh_token
          </code>
        </Paragraph>
        <Input.TextArea
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          rows={12}
          placeholder="可直接粘贴账号内容，或先读取 TXT 后再确认导入。"
          style={{ fontFamily: 'monospace' }}
        />
      </Modal>

      <Modal
        title={selectedAccount ? `邮件列表 - ${selectedAccount.email}` : '邮件列表'}
        open={mailModalOpen}
        onCancel={() => setMailModalOpen(false)}
        footer={null}
        width={1200}
        maskClosable={false}
      >
        <Table
          rowKey="message_id"
          columns={mailColumns}
          dataSource={mails}
          loading={mailLoading}
          size="middle"
          pagination={{ pageSize: 10, showSizeChanger: false }}
          locale={{ emptyText: mailLoading ? '加载中...' : '没有查到邮件' }}
          scroll={{ x: 980 }}
        />
      </Modal>

      <Modal
        title={mailDetail?.subject || '邮件详情'}
        open={!!mailDetail}
        onCancel={() => setMailDetail(null)}
        footer={null}
        width={900}
        maskClosable={false}
      >
        {mailDetail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Space wrap>
              {getFolderTag(mailDetail.folder || '-')}
              <Text type="secondary">发件人：{mailDetail.from || '-'}</Text>
              <Text type="secondary">收件时间：{formatDateTime(mailDetail.received_at)}</Text>
            </Space>
            <Card size="small" title="摘要">
              <div style={{ whiteSpace: 'pre-wrap' }}>{mailDetail.snippet || '-'}</div>
            </Card>
            <Card size="small" title="正文">
              <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {mailDetail.body_text || mailDetail.body_html || mailDetail.snippet || '(无正文)'}
              </div>
            </Card>
          </div>
        )}
      </Modal>
    </div>
  )
}
