const digitsOnly = (value: string | null | undefined) => String(value ?? '').replace(/\D/g, '')

export function formatCpfCnpj(value: string | null | undefined): string {
  const digits = digitsOnly(value).slice(0, 14)
  if (!digits) return ''

  if (digits.length <= 11) {
    return digits
      .replace(/^(\d{3})(\d)/, '$1.$2')
      .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
      .replace(/\.(\d{3})(\d)/, '.$1-$2')
  }

  return digits
    .replace(/^(\d{2})(\d)/, '$1.$2')
    .replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
    .replace(/\.(\d{3})(\d)/, '.$1/$2')
    .replace(/(\/\d{4})(\d)/, '$1-$2')
}

export function formatPhone(value: string | null | undefined): string {
  let digits = digitsOnly(value).slice(0, 13)
  if (!digits) return ''

  let prefix = ''
  if (digits.startsWith('55') && digits.length > 11) {
    prefix = '+55 '
    digits = digits.slice(2)
  }

  digits = digits.slice(0, 11)
  if (digits.length <= 2) return `${prefix}${digits ? `(${digits}` : ''}`

  const ddd = digits.slice(0, 2)
  const local = digits.slice(2)
  if (local.length <= 4) return `${prefix}(${ddd}) ${local}`
  if (local.length <= 8) return `${prefix}(${ddd}) ${local.slice(0, 4)}-${local.slice(4)}`
  return `${prefix}(${ddd}) ${local.slice(0, 5)}-${local.slice(5, 9)}`
}

export function formatCep(value: string | null | undefined): string {
  const digits = digitsOnly(value).slice(0, 8)
  return digits.length > 5 ? `${digits.slice(0, 5)}-${digits.slice(5)}` : digits
}

export function parsePtBrNumber(value: number | string | null | undefined): number | null {
  if (value == null || value === '') return null
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  const text = String(value).trim()
  if (!text) return null
  const normalized = text.includes(',') ? text.replace(/\./g, '').replace(',', '.') : text
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : null
}

export function formatDecimal(value: number | string | null | undefined, fractionDigits = 2): string {
  const parsed = parsePtBrNumber(value)
  if (parsed == null) return '—'
  return parsed.toLocaleString('pt-BR', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  })
}

export function formatCurrency(value: number | string | null | undefined): string {
  const parsed = parsePtBrNumber(value)
  if (parsed == null) return '—'
  return parsed.toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

const documentKeys = new Set(['document_number', 'documentNumber', 'cpf_cnpj', 'cpfCnpj', 'cpf', 'cnpj', 'account_holder_document'])
const phoneKeys = new Set(['phone', 'contact_phone', 'contactPhone', 'whatsapp', 'telefone', 'celular'])
const cepKeys = new Set(['postal_code', 'postalCode', 'cep'])

function formatScalar(key: string, value: unknown): unknown {
  if (typeof value !== 'string') return value
  if (documentKeys.has(key)) return formatCpfCnpj(value)
  if (phoneKeys.has(key)) return formatPhone(value)
  if (cepKeys.has(key)) return formatCep(value)
  return value
}

function normalizeScalar(key: string, value: unknown): unknown {
  if (typeof value !== 'string') return value
  if (documentKeys.has(key) || phoneKeys.has(key) || cepKeys.has(key)) return digitsOnly(value)
  return value
}

function transformObject(value: unknown, mode: 'format' | 'normalize'): unknown {
  if (Array.isArray(value)) return value.map((item) => transformObject(item, mode))
  if (!value || typeof value !== 'object') return value

  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>).map(([key, current]) => {
      if (current && typeof current === 'object') return [key, transformObject(current, mode)]
      return [key, mode === 'format' ? formatScalar(key, current) : normalizeScalar(key, current)]
    }),
  )
}

/**
 * Formata campos brasileiros vindos da API sem alterar tipos numéricos usados
 * nos cálculos do ERP. A interface passa a receber documentos/telefones/CEP
 * prontos para exibição em qualquer módulo.
 */
export function formatApiPayload<T>(value: T): T {
  return transformObject(value, 'format') as T
}

/**
 * Remove pontuação de campos mascarados antes da persistência. Isso mantém o
 * banco canônico (somente dígitos) mesmo que toda a UI trabalhe formatada.
 */
export function normalizeApiPayload<T>(value: T): T {
  return transformObject(value, 'normalize') as T
}

export function normalizeJsonRequest(init: RequestInit): RequestInit {
  if (typeof init.body !== 'string') return init
  try {
    const parsed = JSON.parse(init.body) as unknown
    return { ...init, body: JSON.stringify(normalizeApiPayload(parsed)) }
  } catch {
    return init
  }
}

type MaskKind = 'document' | 'phone' | 'cep'

function labelHint(input: HTMLInputElement): string {
  const label = input.closest('label')
  const directLabel = label?.querySelector(':scope > span')?.textContent ?? label?.textContent ?? ''
  return [
    input.dataset.format ?? '',
    input.name,
    input.id,
    input.getAttribute('aria-label') ?? '',
    input.placeholder,
    directLabel,
  ].filter(Boolean).join(' ').toLowerCase()
}

function maskKind(input: HTMLInputElement): MaskKind | null {
  const type = (input.type || 'text').toLowerCase()
  if (['number', 'date', 'datetime-local', 'month', 'email', 'file', 'password', 'hidden', 'checkbox', 'radio'].includes(type)) return null
  if (/^\s*(buscar|pesquisar|search)/i.test(input.placeholder || '')) return null

  const explicit = input.dataset.format
  if (explicit === 'raw' || explicit === 'none') return null
  if (explicit === 'cpf-cnpj' || explicit === 'document') return 'document'
  if (explicit === 'phone') return 'phone'
  if (explicit === 'cep') return 'cep'

  const hint = labelHint(input)
  if (/\b(cpf|cnpj|cpf\/cnpj|document_number)\b/.test(hint)) return 'document'
  if (/\b(telefone|celular|whatsapp|contact_phone|phone)\b/.test(hint)) return 'phone'
  if (/\b(cep|postal_code|postalcode)\b/.test(hint)) return 'cep'
  return null
}

function applyMask(input: HTMLInputElement): void {
  const kind = maskKind(input)
  if (!kind) return

  const next = kind === 'document'
    ? formatCpfCnpj(input.value)
    : kind === 'phone'
      ? formatPhone(input.value)
      : formatCep(input.value)

  input.inputMode = 'numeric'
  if (next === input.value) return
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  if (setter) setter.call(input, next)
  else input.value = next
}

function isTwoDecimalInput(input: HTMLInputElement): boolean {
  if (input.type !== 'number') return false
  const step = input.getAttribute('step')
  return step === '0.01' || step === '.01' || input.dataset.format === 'decimal-2' || input.dataset.format === 'money'
}

function formatDecimalInput(input: HTMLInputElement): void {
  if (!isTwoDecimalInput(input) || !input.value) return
  const parsed = Number(input.value)
  if (!Number.isFinite(parsed)) return
  input.lang = 'pt-BR'
  const next = parsed.toFixed(2)
  if (next === input.value) return
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  if (setter) setter.call(input, next)
  else input.value = next
}

function prepareInput(input: HTMLInputElement): void {
  applyMask(input)
  if (isTwoDecimalInput(input) && document.activeElement !== input) formatDecimalInput(input)
}

/**
 * Máscaras globais para campos atuais e futuros. O tratamento ocorre antes do
 * onChange do React, então os componentes controlados recebem o valor já
 * formatado sem precisarem duplicar lógica em cada tela.
 */
export function installBrazilianInputFormatting(): () => void {
  document.documentElement.lang = 'pt-BR'

  const onInput = (event: Event) => {
    if (event.target instanceof HTMLInputElement) applyMask(event.target)
  }
  const onFocus = (event: FocusEvent) => {
    if (event.target instanceof HTMLInputElement) prepareInput(event.target)
  }
  const onBlur = (event: FocusEvent) => {
    if (event.target instanceof HTMLInputElement) formatDecimalInput(event.target)
  }

  document.addEventListener('input', onInput, true)
  document.addEventListener('focusin', onFocus, true)
  document.addEventListener('focusout', onBlur, true)

  const prepareTree = (node: Node) => {
    if (node instanceof HTMLInputElement) prepareInput(node)
    if (node instanceof Element) node.querySelectorAll('input').forEach((input) => prepareInput(input))
  }

  const observer = new MutationObserver((records) => {
    for (const record of records) record.addedNodes.forEach(prepareTree)
  })
  observer.observe(document.documentElement, { childList: true, subtree: true })
  prepareTree(document.documentElement)

  return () => {
    observer.disconnect()
    document.removeEventListener('input', onInput, true)
    document.removeEventListener('focusin', onFocus, true)
    document.removeEventListener('focusout', onBlur, true)
  }
}
