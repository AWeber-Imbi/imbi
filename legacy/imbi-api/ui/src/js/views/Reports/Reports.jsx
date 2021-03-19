import React, { Fragment, useContext, useEffect } from 'react'
import { Link, Route } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { Card } from '../../components'
import { Context } from '../../state'

import { NamespaceKPIs } from './NamespaceKPIs'

function Index() {
  const { t } = useTranslation()
  return (
    <div className="flex-grow px-3 py-4">
      <Card className="space-y-3">
        <h1 className="text-gray-700 text-lg">{t('reports.available')}</h1>
        <ul className="list-disc list-inside ml-4 text-gray-600">
          <li>
            <Link to="/ui/reports/namespace-kpis">
              {t('reports.namespaceKPIs.title')}
            </Link>
          </li>
        </ul>
      </Card>
    </div>
  )
}

function Reports() {
  const [state, dispatch] = useContext(Context)
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'terms.reports',
        url: new URL('/ui/reports', state.baseURL)
      }
    })
  }, [])
  return (
    <Fragment>
      <Route path="/ui/reports/" exact={true} component={Index} />
      <Route path="/ui/reports/namespace-kpis" component={NamespaceKPIs} />
    </Fragment>
  )
}
export { Reports }
