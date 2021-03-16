import { NavLink } from 'react-router-dom'
import React, { useContext, useEffect, useState } from 'react'

import { Context } from '../../state'
import { Icon } from '../'
import { setDocumentTitle } from '../../utils'

export function Breadcrumbs() {
  const [content, setContent] = useState(null)
  const [state] = useContext(Context)
  useEffect(() => {
    if (state.breadcrumbs.crumbs.length > 1)
      setContent(
        <nav
          className="bg-white border-b border-gray-200 p-x-2 shadow"
          aria-label="Breadcrumb">
          <ol className="flex-1 flex bg-white max-w-screen-xl w-full text-gray-500 px-4 py-3 space-x-4">
            {state.breadcrumbs.crumbs.map((page, offset) => {
              const hasParams =
                Array.from(
                  page.url.searchParams === undefined
                    ? []
                    : page.url.searchParams.keys()
                ).length > 0
              const url = `${page.url.pathname}${
                hasParams ? '?' + page.url.searchParams.toString() : ''
              }`
              if (offset === state.breadcrumbs.crumbs.length - 1) {
                setDocumentTitle(page.title)
                return (
                  <li
                    className="space-x-2 text-gray-700"
                    key={`breadcrumb-${offset}`}>
                    {page.icon && <Icon icon={page.icon} />}
                    {page.showTitle === true && page.title}
                  </li>
                )
              }
              return (
                <li className="space-x-4" key={`breadcrumb-${offset}`}>
                  <NavLink className="space-x-2 hover:text-gray-700" to={url}>
                    {page.icon && <Icon icon={page.icon} />}
                    {page.showTitle === true && page.title}
                  </NavLink>
                  <Icon icon="fas chevron-right" />
                </li>
              )
            })}
          </ol>
        </nav>
      )
  }, [state.breadcrumbs])
  return content
}
