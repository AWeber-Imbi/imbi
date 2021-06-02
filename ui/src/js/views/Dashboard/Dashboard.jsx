import { Link } from 'react-router-dom'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Icon, Loading } from '../../components/'
import { Context } from '../../state'

import { Feed } from './ActivityFeed/'
import { Namespaces } from './Namespaces/'
import { ProjectTypes } from './Stats/'
import { setDocumentTitle } from '../../utils'

export function Dashboard() {
  const [state, setState] = useState({
    feedReady: false,
    namespacesReady: false,
    projectTypesReady: false
  })
  const [globalState, dispatch] = useContext(Context)
  const { t } = useTranslation()

  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        url: new URL('/ui/', globalState.baseURL)
      }
    })
  }, [])
  setDocumentTitle(t('dashboard.title'))
  const loading =
    state.feedReady !== true &&
    state.namespacesReady !== true &&
    state.projectTypesReady !== true
  return (
    <Fragment>
      {loading && <Loading />}
      <div className={`flex-1 ${loading ? 'hidden' : ''}`}>
        <div className="flex flex-col lg:flex-row lg:items-stretch lg:h-screen-1/2 space-x-0 lg:space-x-3 space-y-3 lg:space-y-0">
          <div className="flex-auto lg:h-full lg:w-8/12 w-full">
            <Namespaces
              onReady={() => {
                setState({ ...state, namespacesReady: true })
              }}
            />
          </div>
          <div className="flex-auto lg:h-full lg:w-4/12 w-full">
            <Feed
              onReady={() => {
                setState({ ...state, feedReady: true })
              }}
            />
          </div>
        </div>
        <ProjectTypes
          onReady={() => {
            setState({ ...state, projectTypesReady: true })
          }}
        />
        {state.feedReady === true &&
          state.namespacesReady === true &&
          state.projectTypesReady === true && (
            <div className="mr-2 pb-3 text-right">
              <Link
                to="/ui/reports/project-type-definitions"
                className="italic text-sm text-gray-600 hover:text-blue-600">
                <Icon icon="fas book-open" className="mr-2" />
                {t('reports.projectTypeDefinitions.title')}
              </Link>
            </div>
          )}
      </div>
    </Fragment>
  )
}
