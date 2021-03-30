import React, { Fragment, useContext, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { Card, ContentArea, Icon } from '../../components'
import { Context } from '../../state'

function ProjectTypeDefinitions() {
  const [state, dispatch] = useContext(Context)
  const { t } = useTranslation()
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        url: new URL('/ui/reports/project-type-definitions', state.baseURL),
        title: 'reports.projectTypeDefinitions.title'
      }
    })
  }, [])
  return (
    <ContentArea
      pageTitle={t('reports.projectTypeDefinitions.title')}
      pageIcon="fas book-open">
      <Card className="font-normal px-4 text-gray-600">
        <dl className="space-y-3">
          {state.metadata.projectTypes.map((projectType, offset) => {
            return (
              <Fragment key={`project-type-${projectType.id}`}>
                <dt className={`font-medium ${offset > 0 ? 'pt-3' : ''}`}>
                  <Icon icon={projectType.icon_class} className="mr-2" />
                  {projectType.name}
                </dt>
                <dd className="italic ml-6">{projectType.description}</dd>
              </Fragment>
            )
          })}
        </dl>
      </Card>
    </ContentArea>
  )
}
export { ProjectTypeDefinitions }
