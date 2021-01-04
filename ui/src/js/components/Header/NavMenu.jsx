import {Link, NavLink} from "react-router-dom"
import {Menu} from "@headlessui/react"
import React from "react"
import PropTypes from "prop-types"
import {useTranslation} from "react-i18next"

import {Icon, Tooltip} from "../"
import {User} from "../../schema"

function MenuItem({children, to}) {
  return (
    <NavLink className="nav-menu-link"
             to={to}>
      {children}
    </NavLink>
  )
}

MenuItem.propTypes = {
  children: PropTypes.oneOfType([PropTypes.string, PropTypes.object]).isRequired,
  to: PropTypes.string.isRequired
}

function NavMenu({currentUser}) {
  const {t} = useTranslation()
  if (currentUser.authenticated === true)
    return (
      <Menu as="div" className="flex-grow ml-2 mt-2 space-x-2">
        <Link className="nav-menu-link" to="/ui/">{t("headerNavItems.dashboard")}</Link>
        <NavLink className="nav-menu-link" to="/ui/projects">{t("headerNavItems.projects")}</NavLink>
        <NavLink className="nav-menu-link" to="/ui/changelog">{t("headerNavItems.changeLog")}</NavLink>
        {currentUser.permissions.includes("admin") && (
          <Tooltip value={t("headerNavItems.administration")}>
            <NavLink className="nav-menu-link" to="/ui/admin">
              <Icon icon="fas wrench" className="p-0 m-0"/>
            </NavLink>
          </Tooltip>
        )}
      </Menu>)
  return null
}

NavMenu.propTypes = {
  currentUser: PropTypes.shape(User)
}

export default NavMenu
