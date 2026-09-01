import { apiRequest } from '../api/client'

type MeResponse = { organization_id: string }

function rewriteLinks(organizationId: string) {
  document.querySelectorAll<HTMLAnchorElement>('a[href]').forEach((anchor) => {
    const raw = anchor.getAttribute('href') ?? ''
    const match = raw.match(/^\/imoveis\/([^/?#]+)/)
    if (!match) return
    anchor.setAttribute('href', `/site/${encodeURIComponent(organizationId)}/imoveis/${encodeURIComponent(match[1])}`)
    anchor.setAttribute('target', '_blank')
    anchor.setAttribute('rel', 'noreferrer')
    anchor.title = anchor.title || 'Abrir anúncio no site público'
  })
}

/** Corrige links antigos de publicação para a rota pública canônica do site. */
export function installPublicSiteLinkEnhancer(): () => void {
  if (/^\/(?:site|portal)\//.test(window.location.pathname)) return () => undefined
  let disposed = false
  let observer: MutationObserver | null = null
  void apiRequest<MeResponse>('/me').then(({ organization_id }) => {
    if (disposed || !organization_id) return
    const apply = () => rewriteLinks(organization_id)
    apply()
    observer = new MutationObserver(apply)
    observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['href'] })
  }).catch(() => undefined)
  return () => { disposed = true; observer?.disconnect() }
}
