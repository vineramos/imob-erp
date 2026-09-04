import { Building2, CalendarDays, CircleDollarSign, ClipboardCheck, FileText, House, LoaderCircle, Search, UserRound, Wrench } from 'lucide-react'
import { KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, apiRequest } from '../api/client'
import './global-search.css'

type SearchResult = {
  id: string
  kind: string
  module: string
  code: string
  title: string
  subtitle: string
  route: string
  meta: string | null
}
type SearchResponse = { query: string; results: SearchResult[] }
type Props = { onNavigate: (module: string, route: string) => void }

const kindLabel: Record<string, string> = {
  person: 'Pessoa', property: 'Imóvel', administration_contract: 'Contrato de administração', lease_contract: 'Contrato de locação',
  inspection: 'Vistoria', maintenance: 'Manutenção', maintenance_partner: 'Parceiro', charge: 'Cobrança', agenda_task: 'Agenda',
}

function ResultIcon({ kind }: { kind: string }) {
  if (kind === 'person') return <UserRound size={16}/>
  if (kind === 'property') return <House size={16}/>
  if (kind === 'inspection') return <ClipboardCheck size={16}/>
  if (kind === 'maintenance') return <Wrench size={16}/>
  if (kind === 'maintenance_partner') return <Building2 size={16}/>
  if (kind === 'charge') return <CircleDollarSign size={16}/>
  if (kind === 'agenda_task') return <CalendarDays size={16}/>
  return <FileText size={16}/>
}

export function GlobalSearch({ onNavigate }: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const requestSequence = useRef(0)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)

  useEffect(() => {
    const keyboard = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen(true)
        requestAnimationFrame(() => inputRef.current?.focus())
      }
      if (event.key === 'Escape' && open) {
        setOpen(false)
        inputRef.current?.blur()
      }
    }
    const outside = (event: PointerEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('keydown', keyboard)
    window.addEventListener('pointerdown', outside)
    return () => {
      window.removeEventListener('keydown', keyboard)
      window.removeEventListener('pointerdown', outside)
    }
  }, [open])

  useEffect(() => {
    const term = query.trim()
    if (term.length < 2) {
      setResults([]); setLoading(false); setError(''); setActiveIndex(0)
      return
    }
    const sequence = ++requestSequence.current
    setLoading(true); setError('')
    const timer = window.setTimeout(async () => {
      try {
        const response = await apiRequest<SearchResponse>(`/search?q=${encodeURIComponent(term)}&limit=28`)
        if (sequence !== requestSequence.current) return
        setResults(response.results)
        setActiveIndex(0)
      } catch (cause) {
        if (sequence !== requestSequence.current) return
        setResults([])
        setError(cause instanceof ApiError ? cause.detail : 'Não foi possível realizar a busca.')
      } finally {
        if (sequence === requestSequence.current) setLoading(false)
      }
    }, 180)
    return () => window.clearTimeout(timer)
  }, [query])

  const groupedHint = useMemo(() => {
    if (!results.length) return ''
    const modules = new Set(results.map(item => item.module))
    return `${results.length} resultado(s) em ${modules.size} módulo(s)`
  }, [results])

  function choose(item: SearchResult) {
    setOpen(false)
    onNavigate(item.module, item.route)
  }

  function onInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault(); setOpen(true); setActiveIndex(current => results.length ? (current + 1) % results.length : 0)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault(); setOpen(true); setActiveIndex(current => results.length ? (current - 1 + results.length) % results.length : 0)
    } else if (event.key === 'Enter' && results[activeIndex]) {
      event.preventDefault(); choose(results[activeIndex])
    }
  }

  return <div className="global-search-shell" ref={wrapperRef}>
    <label className={`global-search ${open ? 'is-open' : ''}`}>
      <Search size={17}/>
      <input
        ref={inputRef}
        aria-label="Busca global"
        aria-expanded={open}
        aria-controls="global-search-results"
        placeholder="Buscar imóveis, contratos, pessoas, cobranças..."
        value={query}
        onFocus={() => setOpen(true)}
        onChange={event => { setQuery(event.target.value); setOpen(true) }}
        onKeyDown={onInputKeyDown}
      />
      {loading ? <LoaderCircle className="global-search-spinner" size={15}/> : <kbd>Ctrl K</kbd>}
    </label>
    {open && <div className="global-search-popover panel" id="global-search-results" role="listbox">
      <div className="global-search-popover-head"><span>Busca em todo o ERP</span><small>{groupedHint || 'Use nome, documento, código, endereço ou descrição'}</small></div>
      {error && <div className="global-search-state danger">{error}</div>}
      {!error && query.trim().length < 2 && <div className="global-search-state">Digite pelo menos 2 caracteres para pesquisar.</div>}
      {!error && query.trim().length >= 2 && !loading && results.length === 0 && <div className="global-search-state">Nenhum registro encontrado com “{query.trim()}”.</div>}
      {results.length > 0 && <div className="global-search-results">{results.map((item, index) => <button
        type="button"
        role="option"
        aria-selected={index === activeIndex}
        className={index === activeIndex ? 'active' : ''}
        key={`${item.kind}-${item.id}`}
        onMouseEnter={() => setActiveIndex(index)}
        onClick={() => choose(item)}
      >
        <span className="global-search-result-icon"><ResultIcon kind={item.kind}/></span>
        <span className="global-search-result-copy"><span><strong>{item.title}</strong><i>{item.code}</i></span><small>{item.subtitle}</small></span>
        <span className="global-search-result-meta"><small>{kindLabel[item.kind] || item.kind}</small>{item.meta && <i>{item.meta}</i>}</span>
      </button>)}</div>}
      <footer><span>↑↓ navegar</span><span>Enter abrir</span><span>Esc fechar</span></footer>
    </div>}
  </div>
}
