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

  const productModal = document.querySelector('#product-modal')
  document.querySelectorAll('[data-edit-product]').forEach((button) => {
    button.addEventListener('click', () => {
      const card = button.closest('[data-product-card]')
      if (!productModal || !card) return
      productModal.dataset.itemId = card.dataset.productId
      productModal.querySelector('[name="product-name"]').value = card.dataset.productName
      productModal.querySelector('[name="product-price"]').value = card.dataset.productPrice
      productModal.querySelector('[name="product-active"]').checked = card.dataset.productActive === 'true'
      productModal.querySelector('[name="product-description"]').value = card.dataset.productDescription || ''
      const category = productModal.querySelector('[name="product-category"]')
      const matchingCategory = [...category.options].find((option) => option.textContent.trim() === card.querySelector('.category-label')?.textContent.trim())
      if (matchingCategory) category.value = matchingCategory.value
    })
  })
  document.querySelector('[data-save-product]')?.addEventListener('click', async () => {
    if (!productModal.dataset.itemId) return showToast('Product creation is not available yet')
    const data = {
      name: productModal.querySelector('[name="product-name"]').value,
      category_id: Number(productModal.querySelector('[name="product-category"]').value),
      price: productModal.querySelector('[name="product-price"]').value,
      active: productModal.querySelector('[name="product-active"]').checked,
      description: productModal.querySelector('[name="product-description"]').value,
    }
    const response = await fetch(`/dashboard/menu-items/${productModal.dataset.itemId}`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) })
    if (!response.ok) return showToast((await response.json()).error || 'Unable to save product')
    const image = productModal.querySelector('[name="product-image"]').files[0]
    if (image) {
      const form = new FormData()
      form.append('image', image)
      const imageResponse = await fetch(`/dashboard/menu-items/${productModal.dataset.itemId}/image`, { method: 'POST', body: form })
      if (!imageResponse.ok) return showToast((await imageResponse.json()).error || 'Unable to upload image')
    }
    window.location.reload()
  })

  const categoryModal = document.querySelector('#category-modal')
  document.querySelectorAll('[data-edit-category]').forEach((button) => {
    button.addEventListener('click', () => {
      categoryModal.dataset.categoryId = button.dataset.categoryId
      categoryModal.querySelector('[name="category-name"]').value = button.dataset.categoryName
      categoryModal.querySelector('[name="category-active"]').checked = button.dataset.categoryActive === 'true'
    })
  })
  document.querySelector('[data-save-category]')?.addEventListener('click', async () => {
    if (!categoryModal.dataset.categoryId) return showToast('Category creation is not available yet')
    const data = {name: categoryModal.querySelector('[name="category-name"]').value, active: categoryModal.querySelector('[name="category-active"]').checked}
    const response = await fetch(`/dashboard/menu-categories/${categoryModal.dataset.categoryId}`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) })
    if (!response.ok) return showToast((await response.json()).error || 'Unable to save category')
    window.location.reload()
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
