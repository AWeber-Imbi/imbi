import Gravatar from 'react-gravatar'
import { Menu } from '@headlessui/react'
import { NavLink } from 'react-router-dom'
import React, { useContext } from 'react'
import PropTypes from 'prop-types'
import { useTranslation } from 'react-i18next'

import { Context } from '../../state'
import { Icon } from '../'
import { User } from '../../schema'

function UserMenuItem({ value, to, icon }) {
  return (
    <Menu.Item>
      <NavLink
        className="user-menu-link"
        key={to.replace(/\//gi, '_') + '-nav-item'}
        to={to}>
        <div className="inline-block w-6 mr-2 text-center">
          <Icon icon={icon} />
        </div>
        {value}
      </NavLink>
    </Menu.Item>
  )
}

UserMenuItem.propTypes = {
  value: PropTypes.string.isRequired,
  to: PropTypes.string.isRequired,
  icon: PropTypes.string.isRequired
}

function UserMenu({ user }) {
  const [state] = useContext(Context)
  const { t } = useTranslation()
  return (
    <Menu as="div" className="flex-shrink mr-3">
      <Menu.Button as={React.Fragment}>
        <button
          className="bg-gray-800 flex my-1 text-sm rounded-full focus:outline-none"
          title={t('headerNavItems.userMenu')}>
          <span className="sr-only">{t('headerNavItems.openUserMenu')}</span>
          <Gravatar
            className="h-8 w-8 rounded-full"
            default="mp"
            email={user.email_address}
            size={22}
          />
        </button>
      </Menu.Button>
      <Menu.Items
        aria-labelledby="user-menu"
        aria-orientation="vertical"
        className="origin-top-right absolute right-3 mt-1 w-48 rounded-md shadow-lg py-1 focus:outline-none bg-white ring-1 ring-gray-300 ring-opacity-5 z-40">
        <UserMenuItem
          to="/ui/user/profile"
          icon="fas id-card"
          value={t('headerNavItems.profile')}
        />
        <UserMenuItem
          to="/ui/user/settings"
          icon="fas user-cog"
          value={t('headerNavItems.settings')}
        />
        <Menu.Item>
          <a
            className="user-menu-link"
            href="/ui/logout"
            onClick={(event) => {
              event.preventDefault()
              state.handleLogout()
            }}>
            <div className="inline-block w-6 mr-2 text-center">
              <Icon icon="fas sign-out-alt" />
            </div>
            {t('headerNavItems.signOut')}
          </a>
        </Menu.Item>
      </Menu.Items>
    </Menu>
  )
}

UserMenu.propTypes = {
  user: PropTypes.shape(User)
}

export { UserMenu }
