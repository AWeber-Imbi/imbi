import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ContentArea, Error, Loading, Stats } from '../components/'
import { httpGet, setDocumentTitle } from '../utils'
import { FetchContext } from '../contexts'

export function Dashboard() {
  const { t } = useTranslation()
  const [data, setData] = useState(null)
  const [errorMessage, setErrorMessage] = useState(null)
  const fetch = useContext(FetchContext)

  setDocumentTitle(t('headerNavItems.dashboard'))

  useEffect(() => {
    if (data === null) {
      const url = new URL(fetch.baseURL)
      url.pathname = `/dashboard`
      httpGet(
        fetch.function,
        url,
        (result) => {
          setData(result)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [data])

  if (errorMessage !== null) return <Error>{errorMessage}</Error>
  return (
    <Fragment>
      {data === null && <Loading />}
      {data !== null && (
        <ContentArea
          pageIcon="fas chart-line"
          pageTitle={t('dashboard.projectTypes')}>
          <Stats.Container>
            {data.project_types.map((row) => {
              return (
                <Stats.Value
                  key={`stats-${row.name}`}
                  title={row.count === 1 ? row.name : row.plural}
                  icon={row.icon}
                  url={`/ui/projects?project_type=${row.project_type_id}`}
                  value={row.count}
                />
              )
            })}
          </Stats.Container>
        </ContentArea>
      )}
    </Fragment>
  )
}
