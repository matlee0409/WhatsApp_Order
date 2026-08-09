document.addEventListener('DOMContentLoaded', () => {
  const sidebar = document.querySelector('#sidebar')
  const menuToggle = document.querySelector('[data-menu-toggle]')
  const closeMenu = () => {
    sidebar?.classList.remove('open')
    menuToggle?.setAttribute('aria-expanded', 'false')
  }
  menuToggle?.addEventListener('click', () => {
    const open = sidebar?.classList.toggle('open')
    menuToggle.setAttribute('aria-expanded', String(Boolean(open)))
  })
  document.querySelector('[data-close-menu]')?.addEventListener('click', closeMenu)

  document.querySelector('[data-password-toggle]')?.addEventListener('click', (event) => {
    const input = document.querySelector('#password')
    const showing = input?.type === 'text'
    if (input) input.type = showing ? 'password' : 'text'
    event.currentTarget.textContent = showing ? 'Show' : 'Hide'
    event.currentTarget.setAttribute('aria-label', showing ? 'Show password' : 'Hide password')
  })

  let toastTimer
  const showToast = (message) => {
    const toast = document.querySelector('.toast')
    if (!toast) return
    toast.textContent = message
    toast.hidden = false
    clearTimeout(toastTimer)
    toastTimer = setTimeout(() => { toast.hidden = true }, 2400)
  }
  document.querySelectorAll('[data-toast]').forEach((element) => {
    element.addEventListener('click', () => showToast(element.dataset.toast))
  })

  const closeModal = (modal) => {
    if (!modal) return
    modal.hidden = true
    document.body.style.overflow = ''
  }
  document.querySelectorAll('[data-modal-open]').forEach((button) => {
    button.addEventListener('click', () => {
      const modal = document.querySelector(`#${button.dataset.modalOpen}-modal`)
      if (!modal) return
      modal.hidden = false
      document.body.style.overflow = 'hidden'
      modal.querySelector('input, select, textarea, button')?.focus()
    })
  })
  document.querySelectorAll('[data-modal-close]').forEach((button) => {
    button.addEventListener('click', () => closeModal(button.closest('.modal')))
  })
  document.querySelectorAll('.modal').forEach((modal) => {
    modal.addEventListener('click', (event) => { if (event.target === modal) closeModal(modal) })
  })
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeMenu()
      closeModal(document.querySelector('.modal:not([hidden])'))
    }
  })

  const filterCards = (selector, value) => {
    document.querySelectorAll(selector).forEach((card) => {
      card.hidden = !card.dataset.search.toLowerCase().includes(value.toLowerCase())
    })
  }
  document.querySelector('[data-order-search]')?.addEventListener('input', (event) => filterCards('[data-order-card]', event.target.value))
  document.querySelector('[data-product-search]')?.addEventListener('input', (event) => filterCards('[data-product-card]', event.target.value))

  document.querySelectorAll('.switch input').forEach((input) => {
    input.addEventListener('change', () => {
      const label = input.closest('.switch')?.querySelector('em')
      if (label) label.textContent = input.checked ? 'Available' : 'Hidden'
    })
  })

  document.querySelectorAll('.eta-control').forEach((control) => {
    const buttons = control.querySelectorAll('button')
    const output = control.querySelector('b')
    buttons.forEach((button, index) => button.addEventListener('click', () => {
      const current = parseInt(output.textContent, 10)
      output.textContent = `${Math.max(1, current + (index === 0 ? -1 : 1))} min`
    }))
  })

  let dragged
  const statuses = ['new', 'preparing', 'ready', 'completed']
  const moveCard = (card) => {
    const column = card.closest('.kanban-column')
    const index = statuses.indexOf(column?.dataset.status)
    const next = document.querySelector(`.kanban-column[data-status="${statuses[index + 1]}"] [data-drop-zone]`)
    if (next) {
      next.prepend(card)
      showToast('Order moved forward')
      updateCounts()
    } else showToast('Order details opened')
  }
  const updateCounts = () => document.querySelectorAll('.kanban-column').forEach((column) => {
    const count = column.querySelectorAll('[data-order-card]:not([hidden])').length
    const badge = column.querySelector('.count-badge')
    if (badge) badge.textContent = count
  })
  document.querySelectorAll('[data-order-card]').forEach((card) => {
    card.addEventListener('dragstart', () => { dragged = card; card.classList.add('dragging') })
    card.addEventListener('dragend', () => card.classList.remove('dragging'))
    card.querySelector('[data-advance-order]')?.addEventListener('click', () => moveCard(card))
  })
  document.querySelectorAll('[data-drop-zone]').forEach((zone) => {
    zone.addEventListener('dragover', (event) => event.preventDefault())
    zone.addEventListener('drop', (event) => {
      event.preventDefault()
      if (dragged) { zone.prepend(dragged); updateCounts(); showToast('Order status updated') }
    })
  })
})
