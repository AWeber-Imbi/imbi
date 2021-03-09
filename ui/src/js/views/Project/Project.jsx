import React, { useContext, useEffect, useState } from 'react'
import { Route, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { FetchContext } from '../../contexts'
import { httpGet, setDocumentTitle } from '../../utils'
import { Icon, Loading, Tabs } from '../../components'

import { Overview } from './Overview'
import { Edit } from './Edit'

function Project() {
  const { t } = useTranslation()
  const [errorMessage, setErrorMessage] = useState(null)
  const fetch = useContext(FetchContext)
  const { projectId } = useParams()
  const [project, setProject] = useState({})
  const [factTypes, setFactTypes] = useState(undefined)

  useEffect(() => {
    if (project.id === undefined) {
      const url = new URL(fetch.baseURL)
      url.pathname = `/projects/${projectId}`
      url.searchParams.append('full', 'true')
      httpGet(
        fetch.function,
        url,
        (result) => {
          setProject(result)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [projectId, project])

  useEffect(() => {
    if (factTypes === undefined) {
      const url = new URL(fetch.baseURL)
      url.pathname = `/projects/${projectId}/fact-types`
      httpGet(
        fetch.function,
        url,
        (result) => {
          setFactTypes(result)
        },
        (error) => {
          setErrorMessage(error)
        }
      )
    }
  }, [projectId, factTypes])

  if (project.name === undefined) {
    setDocumentTitle(t('common.loading'))
    return <Loading />
  }

  console.log(errorMessage)

  setDocumentTitle(project.name)

  return (
    <div className="flex-auto px-6 py-4">
      <h1 className="text-gray-600 text-xl">
        <Icon icon={project.project_icon} className="ml-2 mr-2" />
        {project.name}
      </h1>

      <div className="my-4 bg-white px-4 py-2 border-b border-gray-200 rounded-md">
        <Tabs.TabBar>
          <Tabs.Tab target={`/ui/projects/${projectId}`}>Overview</Tabs.Tab>
          <Tabs.Tab target={`/ui/projects/${projectId}/dependencies`}>
            Dependencies
          </Tabs.Tab>
          <Tabs.Tab target={`/ui/projects/${projectId}/logs`}>Logs</Tabs.Tab>
          <Tabs.Tab target={`/ui/projects/${projectId}/operations-log`}>
            Operations Log
          </Tabs.Tab>
          <Tabs.Tab target={`/ui/projects/${projectId}/configuration`}>
            Configuration
          </Tabs.Tab>
          <Tabs.Tab target={`/ui/projects/${projectId}/fact-history`}>
            Fact History
          </Tabs.Tab>
          <Tabs.Tab target={`/ui/projects/${projectId}/edit`}>Edit</Tabs.Tab>
        </Tabs.TabBar>
        <Tabs.Container>
          <Route path={`/ui/projects/${projectId}`} exact>
            <Overview project={project} />
          </Route>
          <Route path={`/ui/projects/${projectId}/logs`}>
            <div>Logs</div>
          </Route>
          <Route path={`/ui/projects/${projectId}/edit`}>
            <Edit project={project} />
          </Route>
        </Tabs.Container>
      </div>
    </div>
  )
}

Project.propTypes = {}

export { Project }
