import { ApiError, apiBlobRequest } from '../api/client'

let installed = false

function protectedPdfPath(href: string): string | null {
  const url = new URL(href, window.location.origin)
  if (url.origin !== window.location.origin) return null
  if (!url.pathname.startsWith('/api/')) return null
  if (!url.pathname.endsWith('/pdf')) return null
  return `${url.pathname.slice('/api'.length)}${url.search}`
}

function renderPopupMessage(popup: Window, title: string, message: string) {
  try {
    popup.document.title = title
    popup.document.body.replaceChildren()
    popup.document.body.style.margin = '0'
    popup.document.body.style.minHeight = '100vh'
    popup.document.body.style.display = 'grid'
    popup.document.body.style.placeItems = 'center'
    popup.document.body.style.background = '#f5f7fa'
    popup.document.body.style.fontFamily = 'Inter, ui-sans-serif, system-ui, sans-serif'
    popup.document.body.style.color = '#132238'

    const card = popup.document.createElement('div')
    card.style.maxWidth = '440px'
    card.style.padding = '28px 32px'
    card.style.border = '1px solid #dfe6ee'
    card.style.borderRadius = '14px'
    card.style.background = '#ffffff'
    card.style.boxShadow = '0 12px 36px rgba(17, 36, 61, .08)'
    card.style.textAlign = 'center'

    const heading = popup.document.createElement('strong')
    heading.textContent = title
    heading.style.display = 'block'
    heading.style.fontSize = '16px'
    heading.style.marginBottom = '8px'

    const text = popup.document.createElement('span')
    text.textContent = message
    text.style.display = 'block'
    text.style.fontSize = '13px'
    text.style.lineHeight = '1.5'
    text.style.color = '#66758a'

    card.append(heading, text)
    popup.document.body.append(card)
  } catch {
    // A aba pode ter sido fechada pelo usuário durante o carregamento.
  }
}

export function installAuthenticatedPdfLinkHandler() {
  if (installed) return
  installed = true

  document.addEventListener('click', (event) => {
    if (!(event instanceof MouseEvent) || event.defaultPrevented || event.button !== 0) return
    const element = event.target instanceof Element ? event.target : null
    const anchor = element?.closest<HTMLAnchorElement>('a[href]')
    if (!anchor) return

    const path = protectedPdfPath(anchor.href)
    if (!path) return

    event.preventDefault()
    const popup = window.open('about:blank', '_blank')
    if (popup) {
      popup.opener = null
      renderPopupMessage(popup, 'Carregando PDF…', 'Aguarde enquanto o Imob prepara a visualização autenticada do documento.')
    }

    void (async () => {
      try {
        const responseBlob = await apiBlobRequest(path)
        const pdfBlob = responseBlob.type === 'application/pdf'
          ? responseBlob
          : new Blob([responseBlob], { type: 'application/pdf' })
        const objectUrl = URL.createObjectURL(pdfBlob)

        if (popup && !popup.closed) {
          popup.location.replace(objectUrl)
        } else {
          const fallback = document.createElement('a')
          fallback.href = objectUrl
          fallback.target = '_blank'
          fallback.rel = 'noopener noreferrer'
          fallback.click()
        }

        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
      } catch (cause) {
        const message = cause instanceof ApiError ? cause.detail : 'Não foi possível carregar este PDF.'
        if (popup && !popup.closed) renderPopupMessage(popup, 'Não foi possível abrir o PDF', message)
        else window.alert(message)
      }
    })()
  }, true)
}
