import { NavLink } from 'react-router-dom'
import { Menu } from '@headlessui/react'
import React from 'react'
import PropTypes from 'prop-types'
import { useTranslation } from 'react-i18next'

import { Icon } from '../'
import { User } from '../../schema'

function NewMenuItem({ value, to }) {
  return (
    <Menu.Item>
      <NavLink
        className="new-menu-link"
        key={to.replace(/\//gi, '_') + '-nav-item'}
        to={to}>
        {value}
      </NavLink>
    </Menu.Item>
  )
}

NewMenuItem.propTypes = {
  value: PropTypes.string.isRequired,
  to: PropTypes.string.isRequired
}

function NewMenu({ user }) {
  const { t } = useTranslation()
  return (
    <Menu as="div" className="flex-shrink mr-3">
      <Menu.Button
        as="button"
        className="bg-blue-700 hover:bg-blue-600 border border-blue-200 text-white hover:text-white px-3 py-1.5 rounded-md mr-5">
        <Icon icon="fas plus-circle" />
        <Icon icon="fas caret-down" className="ml-3" />
      </Menu.Button>
      <Menu.Items
        aria-labelledby="user-menu"
        aria-orientation="vertical"
        className="origin-top-right absolute right-20 mt-1 w-48 rounded-md shadow-lg py-1 focus:outline-none bg-white ring-1 ring-gray-300 ring-opacity-5 z-40">
        <NewMenuItem
          to="/ui/operations-log/create"
          value={t('headerNavItems.newOperationsLogEntry')}
        />
        <NewMenuItem
          to="/ui/projects/create"
          value={t('headerNavItems.newProject')}
        />
        {user.integrations.includes('gitlab') && (
          <NewMenuItem
            to="/ui/projects/import"
            value={t('headerNavItems.importProject')}
          />
        )}
      </Menu.Items>
    </Menu>
  )
}

NewMenu.propTypes = {
  user: PropTypes.shape(User)
}

export { NewMenu }
