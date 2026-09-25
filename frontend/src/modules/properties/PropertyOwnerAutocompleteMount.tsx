import { useEffect } from 'react'

function optionLabel(select: HTMLSelectElement) {
  return select.selectedOptions[0]?.textContent?.trim() || 'Digite para buscar um proprietário'
}

function normalize(value: string) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '')
}

function enhance(select: HTMLSelectElement) {
  const currentUi = select.previousElementSibling
  if (select.dataset.ownerAutocomplete === 'true' && currentUi instanceof HTMLElement && currentUi.dataset.ownerAutocompleteUi === 'true') return
  select.dataset.ownerAutocomplete = 'true'
  select.classList.add('property-owner-native-select')
  select.tabIndex = -1
  select.setAttribute('aria-hidden', 'true')
  Object.assign(select.style, {
    position: 'absolute',
    width: '1px',
    height: '1px',
    margin: '0',
    padding: '0',
    opacity: '0',
    pointerEvents: 'none',
  })

  const wrapper = document.createElement('div')
  wrapper.className = 'property-owner-combobox'
  wrapper.dataset.ownerAutocompleteUi = 'true'

  const searchbox = document.createElement('div')
  searchbox.className = 'property-owner-searchbox'
  searchbox.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.35-4.35"></path></svg>'

  const input = document.createElement('input')
  input.type = 'text'
  input.autocomplete = 'off'
  input.placeholder = 'Digite nome, CPF/CNPJ ou e-mail...'
  input.setAttribute('role', 'combobox')
  input.setAttribute('aria-autocomplete', 'list')
  input.setAttribute('aria-expanded', 'false')
  input.value = optionLabel(select)
  searchbox.appendChild(input)

  const results = document.createElement('div')
  results.className = 'property-owner-results'
  results.setAttribute('role', 'listbox')
  results.hidden = true

  wrapper.append(searchbox, results)
  select.parentElement?.insertBefore(wrapper, select)

  const render = () => {
    const term = normalize(input.value)
    results.replaceChildren()
    const options = Array.from(select.options)
      .filter((option) => !term || normalize(option.textContent || '').includes(term))
      .slice(0, 30)

    if (!options.length) {
      const empty = document.createElement('div')
      empty.className = 'property-owner-no-results'
      empty.textContent = 'Nenhuma pessoa encontrada. Refine a busca.'
      results.appendChild(empty)
    } else {
      options.forEach((option) => {
        const button = document.createElement('button')
        button.type = 'button'
        button.setAttribute('role', 'option')
        const raw = option.textContent?.trim() || ''
        const [name, ...detail] = raw.split(' · ')
        const strong = document.createElement('strong')
        strong.textContent = name
        const span = document.createElement('span')
        span.textContent = detail.join(' · ') || 'Documento não informado'
        button.append(strong, span)
        button.addEventListener('mousedown', (event) => event.preventDefault())
        button.addEventListener('click', () => {
          const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set
          setter?.call(select, option.value)
          select.dispatchEvent(new Event('change', { bubbles: true }))
          input.value = raw
          results.hidden = true
          input.setAttribute('aria-expanded', 'false')
        })
        results.appendChild(button)
      })
    }
    results.hidden = false
    input.setAttribute('aria-expanded', 'true')
  }

  input.addEventListener('focus', () => {
    input.value = ''
    render()
  })
  input.addEventListener('input', render)
  input.addEventListener('blur', () => {
    window.setTimeout(() => {
      results.hidden = true
      input.setAttribute('aria-expanded', 'false')
      input.value = optionLabel(select)
    }, 120)
  })
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      results.hidden = true
      input.setAttribute('aria-expanded', 'false')
      input.value = optionLabel(select)
      input.blur()
    }
  })
  select.addEventListener('change', () => { input.value = optionLabel(select) })
}

export function PropertyOwnerAutocompleteMount() {
  useEffect(() => {
    const sync = () => {
      document.querySelectorAll<HTMLSelectElement>('.property-owner-edit-row > select').forEach(enhance)
    }
    const observer = new MutationObserver(sync)
    observer.observe(document.body, { childList: true, subtree: true })
    sync()
    return () => observer.disconnect()
  }, [])

  return null
}
