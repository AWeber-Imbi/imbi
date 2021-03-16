/*
const rootBreadcrumbs = [
  { path: '/ui/projects/', crumb: { title: 'Projects' } },
  { path: '/ui/admin/', crumb: { title: 'Admin' } },
  {
    path: '/ui/',
    crumbs: { display: false },
    crumb: { title: 'Dashboard', showTitle: false, icon: 'fas house' }
  }
]*/

export function processBreadcrumbs() {
  return {
    display: false,
    crumbs: []
  }
}
