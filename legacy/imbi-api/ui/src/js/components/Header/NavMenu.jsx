import { Link, NavLink, useRouteMatch } from 'react-router-dom'
import { Menu } from '@headlessui/react'
import React from 'react'
import PropTypes from 'prop-types'
import { useTranslation } from 'react-i18next'

import { Icon, Tooltip } from '../'
import { User } from '../../schema'

function MenuItem({ children, to }) {
  return (
    <NavLink className="nav-menu-link" to={to}>
      {children}
    </NavLink>
  )
}

MenuItem.propTypes = {
  children: PropTypes.oneOfType([PropTypes.string, PropTypes.object])
    .isRequired,
  to: PropTypes.string.isRequired
}

function NavMenu({ user }) {
  const match = useRouteMatch({
    path: '/ui/',
    exact: true
  })
  const { t } = useTranslation()

  return (
    <Menu as="div" className={'flex-grow ml-2 mt-2 space-x-2'}>
      <Link className={'nav-menu-link' + (match ? ' active' : '')} to="/ui/">
        {t('dashboard.title')}
      </Link>
      <NavLink className="nav-menu-link" to="/ui/projects">
        {t('projects.title')}
      </NavLink>
      <NavLink className="nav-menu-link" to="/ui/operations-log">
        {t('operationsLog.title')}
      </NavLink>
      <NavLink className="nav-menu-link" to="/ui/reports">
        {t('terms.reports')}
      </NavLink>
      {user.permissions.includes('admin') && (
        <Tooltip value={t('admin.title')}>
          <NavLink className="nav-menu-link" to="/ui/admin">
            <Icon icon="fas wrench" className="p-0 m-0" />
          </NavLink>
        </Tooltip>
      )}
    </Menu>
  )
}

NavMenu.propTypes = {
  user: PropTypes.shape(User)
}

export { NavMenu }
