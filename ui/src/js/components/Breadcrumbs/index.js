const rootBreadcrumbs = [
  {
    path: '/ui/',
    displayBreadcrumbs: false,
    crumb: {
      title: 'headerNavItems.dashboard',
      hideTitle: true,
      icon: 'fas home'
    }
  },
  { path: '/ui/admin', crumb: { title: 'admin.title' } },
  { path: '/ui/operations-log', crumb: { title: 'operationsLog.title' } },
  { path: '/ui/projects', crumb: { title: 'projects.title' } },
  { path: '/ui/reports', crumb: { title: 'terms.reports' } }
]

export function processBreadcrumbs(breadcrumbs, crumb) {
  let crumbs = []
  let display = true
  let rootMatch = false

  breadcrumbs.some((current) => {
    if (
      crumb.url.pathname === current.url.pathname ||
      !crumb.url.pathname.startsWith(current.url.pathname)
    )
      return true
    crumbs.push(current)
  })
  if (crumbs.length === 0)
    rootBreadcrumbs.some((rb) => {
      if (crumb.url.pathname === rb.path) return true
      else if (crumb.url.pathname.startsWith(rb.path)) {
        const parent = new URL(crumb.url)
        parent.pathname = rb.path
        crumbs.push({ ...rb.crumb, url: parent })
      }
    })
  if (crumbs.length === 0) {
    rootMatch = rootBreadcrumbs.some((rb) => {
      if (crumb.url.pathname === rb.path) {
        crumbs.push({ ...rb.crumb, url: crumb.url })
        if (rb.displayBreadcrumbs !== undefined) display = rb.displayBreadcrumbs
        return true
      }
    })
  }
  if (!rootMatch) crumbs.push(crumb)
  return {
    display: display,
    crumbs: crumbs
  }
}
