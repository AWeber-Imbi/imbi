import { NavLink } from 'react-router-dom'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Context } from '../../state'
import { Icon } from '../'
import { setDocumentTitle } from '../../utils'

export function Breadcrumbs() {
  const [content, setContent] = useState(null)
  const [state] = useContext(Context)
  const { t } = useTranslation()

  useEffect(() => {
    if (state.breadcrumbs.display === true)
      setContent(
        <nav
          className="bg-white border-b border-gray-200 p-x-2 shadow"
          aria-label="Breadcrumb">
          <ol className="flex-1 flex bg-white max-w-screen-xl w-full text-gray-500 px-4 py-3 space-x-4">
            {state.breadcrumbs.crumbs.map((crumb, offset) => {
              const hasParams =
                Array.from(
                  crumb.url.searchParams === undefined
                    ? []
                    : crumb.url.searchParams.keys()
                ).length > 0
              const url = `${crumb.url.pathname}${
                hasParams ? '?' + crumb.url.searchParams.toString() : ''
              }`
              if (offset === state.breadcrumbs.crumbs.length - 1) {
                setDocumentTitle(t(crumb.title))
                return (
                  <li
                    className="space-x-2 text-gray-700"
                    key={`breadcrumb-${offset}`}>
                    {crumb.icon && <Icon icon={crumb.icon} />}
                    {crumb.hideTitle !== true && t(crumb.title)}
                  </li>
                )
              }
              return (
                <li className="space-x-4" key={`breadcrumb-${offset}`}>
                  <NavLink className="space-x-2 hover:text-gray-700" to={url}>
                    {crumb.icon && <Icon icon={crumb.icon} />}
                    {crumb.hideTitle !== true && t(crumb.title)}
                  </NavLink>
                  <Icon icon="fas chevron-right" />
                </li>
              )
            })}
          </ol>
        </nav>
      )
    else setContent(<Fragment />)
  }, [state.breadcrumbs])
  return content
}
