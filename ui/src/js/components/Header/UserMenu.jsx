import Gravatar from "react-gravatar"
import {Link} from "@reach/router"
import {Menu} from "@headlessui/react"
import React from "react"
import PropTypes from "prop-types"
import {useTranslation} from "react-i18next"

import {Icon} from "../"
import {User} from "../../schema"

const menuClasses = "block px-4 py-2 text-gray-600 hover:bg-gray-100 hover:text-blue-700 focus:outline-none text-sm"

function UserMenuItem({value, to, icon}) {
  const itemClass = {
    true: menuClasses + " font-bold",
    false: menuClasses
  }
  return (
    <Menu.Item>
      <Link getProps={({isCurrent}) => {return {className: itemClass[isCurrent]}}}
            key={to.replace(/\//gi, "_") + "-nav-item"}
            to={to}>
        <div className="inline-block w-6 mr-2 text-center">
          <Icon icon={icon}/>
        </div>
        {value}
      </Link>
    </Menu.Item>
  )
}

UserMenuItem.propTypes = {
  value: PropTypes.string.isRequired,
  to: PropTypes.string.isRequired,
  icon: PropTypes.string.isRequired
}

function UserMenu({currentUser}) {
  const {t} = useTranslation()
  if (currentUser.authenticated === true)
    return (
      <Menu as="div" className="flex-shrink mr-3">
        <Menu.Button as={React.Fragment}>
          <button className="bg-gray-800 flex my-1 text-sm rounded-full focus:outline-none" title={t("headerNavItems.userMenu")}>
            <span className="sr-only">{t("headerNavItems.openUserMenu")}</span>
            <Gravatar className="h-8 w-8 rounded-full"
                      default="mp"
                      email={currentUser.email_address}
                      size={22}/>
          </button>
        </Menu.Button>
        <Menu.Items aria-labelledby="user-menu"
                    aria-orientation="vertical"
                    className="origin-top-right absolute right-3 mt-1 w-48 rounded-md shadow-lg py-1 focus:outline-none bg-white ring-1 ring-gray-300 ring-opacity-5">
          <UserMenuItem to="/ui/user/profile" icon="fas id-card" value={t("headerNavItems.profile")}/>
          <UserMenuItem to="/ui/user/settings" icon="fas user-cog" value={t("headerNavItems.settings")}/>
          <Menu.Item>
            <a className={menuClasses} href="/ui/logout">
              <div className="inline-block w-6 mr-2 text-center">
                <Icon icon="fas sign-out-alt"/>
              </div>
              {t("headerNavItems.signOut")}
            </a>
          </Menu.Item>
        </Menu.Items>
      </Menu>
    )
  return null
}

UserMenu.propTypes = {
  currentUser: PropTypes.shape(User)
}

export default UserMenu
