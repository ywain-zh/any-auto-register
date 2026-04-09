import { Card, Form, Input, Select, Switch, Typography } from 'antd'
import { parseBooleanConfigValue } from '@/lib/configValueParsers'

export type ProviderOption = {
  label: string
  value: string
}

export type ProviderField = {
  key: string
  label: string
  placeholder?: string
  type?: 'select' | 'input' | 'boolean' | 'textarea'
  secret?: boolean
  required?: boolean
  options?: ProviderOption[]
}

export type MailboxProviderMeta = {
  key: string
  label: string
  description?: string
  fields: ProviderField[]
}

export function normalizeDomainList(input: unknown): string[] {
  const items = Array.isArray(input) ? input : []
  const seen = new Set<string>()
  const domains: string[] = []
  for (const item of items) {
    const domain = String(item || '').trim().toLowerCase().replace(/^@/, '')
    if (!domain || seen.has(domain)) continue
    seen.add(domain)
    domains.push(domain)
  }
  return domains
}

export function parseStoredDomainList(value: unknown): string[] {
  if (Array.isArray(value)) return normalizeDomainList(value)
  if (typeof value !== 'string') return []

  const text = value.trim()
  if (!text) return []

  try {
    const parsed = JSON.parse(text)
    if (Array.isArray(parsed)) {
      return normalizeDomainList(parsed)
    }
  } catch {}

  return normalizeDomainList(
    text
      .split('\n')
      .flatMap((line) => line.split(','))
      .map((item) => item.trim()),
  )
}

export function getProviderFormInitialValues(provider: MailboxProviderMeta | null | undefined, config: Record<string, any> = {}) {
  const values = { ...config }
  if (!provider) return values

  provider.fields.forEach((field) => {
    if (field.type === 'boolean') {
      values[field.key] = parseBooleanConfigValue(values[field.key])
    }
  })

  if (provider.key === 'cfworker') {
    values.cfworker_domains = parseStoredDomainList(values.cfworker_domains)
    values.cfworker_enabled_domains = parseStoredDomainList(values.cfworker_enabled_domains)
    values.cfworker_random_subdomain = parseBooleanConfigValue(values.cfworker_random_subdomain)
  }

  return values
}

export function normalizeProviderConfig(provider: MailboxProviderMeta | null | undefined, formValues: Record<string, any>) {
  if (!provider) {
    return { config: {}, normalizedFormValues: {}, domains: [], enabledDomains: [] }
  }

  const config = Object.fromEntries(provider.fields.map((field) => [field.key, formValues[field.key] ?? '']))

  provider.fields.forEach((field) => {
    if (field.type === 'boolean') {
      config[field.key] = parseBooleanConfigValue(config[field.key])
      return
    }

    if (typeof config[field.key] === 'string') {
      config[field.key] = config[field.key].trim()
    }
  })

  if (provider.key === 'gmail_alias') {
    const appPassword = String(config.gmail_alias_app_password || '').replace(/\s+/g, '')
    if (appPassword && !/^[a-zA-Z]{16}$/.test(appPassword)) {
      throw new Error('Gmail 授权密码格式不正确，应为 16 位字母')
    }
    config.gmail_alias_app_password = appPassword
  }

  let domains: string[] = []
  let enabledDomains: string[] = []

  if (provider.key === 'cfworker') {
    domains = normalizeDomainList(config.cfworker_domains)
    enabledDomains = normalizeDomainList(config.cfworker_enabled_domains).filter((domain) => domains.includes(domain))

    config.cfworker_domains = JSON.stringify(domains)
    config.cfworker_enabled_domains = JSON.stringify(enabledDomains)
    config.cfworker_random_subdomain = parseBooleanConfigValue(config.cfworker_random_subdomain)
    if (domains.length > 0) {
      config.cfworker_domain = ''
    }
  }

  return {
    config,
    normalizedFormValues: {
      ...getProviderFormInitialValues(provider, config),
      ...(provider.key === 'cfworker'
        ? {
            cfworker_domain: domains.length > 0 ? '' : config.cfworker_domain,
            cfworker_domains: domains,
            cfworker_enabled_domains: enabledDomains,
          }
        : {}),
    },
    domains,
    enabledDomains,
  }
}

function ConfigField({ field }: { field: ProviderField }) {
  const isBooleanField = field.type === 'boolean'
  const isTextArea = field.type === 'textarea'

  return (
    <Form.Item
      label={field.label}
      name={field.key}
      valuePropName={isBooleanField ? 'checked' : undefined}
      rules={field.required ? [{ required: true, message: `请输入${field.label}` }] : undefined}
    >
      {field.options?.length ? (
        <Select options={field.options} style={{ width: '100%' }} />
      ) : isBooleanField ? (
        <Switch checkedChildren="开启" unCheckedChildren="关闭" />
      ) : field.secret ? (
        <Input.Password placeholder={field.placeholder} />
      ) : isTextArea ? (
        <Input.TextArea placeholder={field.placeholder} autoSize={{ minRows: 3, maxRows: 6 }} />
      ) : (
        <Input placeholder={field.placeholder} />
      )}
    </Form.Item>
  )
}

export function ProviderConfigFields({ provider }: { provider: MailboxProviderMeta | null | undefined }) {
  if (!provider) return null

  if (!provider.fields.length) {
    return (
      <Card style={{ marginTop: 8 }}>
        <Typography.Text type="secondary">当前 Provider 无需额外配置字段。</Typography.Text>
      </Card>
    )
  }

  return (
    <Card
      title={provider.label}
      extra={provider.description ? <span style={{ fontSize: 12, color: '#7a8ba3' }}>{provider.description}</span> : null}
      style={{ marginTop: 8 }}
    >
      {provider.fields.map((field) => (
        <ConfigField key={field.key} field={field} />
      ))}
    </Card>
  )
}
