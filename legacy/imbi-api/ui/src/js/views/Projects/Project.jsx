import React, { useContext, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { FetchContext } from '../../contexts'
import { httpGet, setDocumentTitle } from '../../utils'
import { Alert, Badge, Icon, IconBar, Loading, Tooltip } from '../../components'

function Project() {
  const { t } = useTranslation()
  const [errorMessage, setErrorMessage] = useState(null)
  const fetch = useContext(FetchContext)
  const { projectId } = useParams()
  const [project, setProject] = useState({})

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

  if (project.name === undefined) {
    setDocumentTitle(t('common.loading'))
    return <Loading />
  }

  setDocumentTitle(project.name)

  return (
    <div className="flex-auto px-6 py-4">
      {errorMessage !== null && <Alert level="error">{errorMessage}</Alert>}
      <div className="flex flex-row">
        <h1 className="flex-auto text-gray-600 text-xl">
          <Icon icon={project.project_icon} className="ml-2 mr-2" />
          {project.name}
        </h1>
        <div className="flex-auto ml-10 space-x-2 text-right">
          {project.orchestration_system && (
            <Tooltip value="Orchestration System">
              <Badge color="blue">
                <Icon
                  icon={project.orchestration_system_icon}
                  className="mr-1"
                />
                {project.orchestration_system}
              </Badge>
            </Tooltip>
          )}
          {project.deployment_type && (
            <Tooltip value="Deployment Type">
              <Badge color="green">
                <Icon icon={project.deployment_type_icon} className="mr-1" />
                {project.deployment_type}
              </Badge>
            </Tooltip>
          )}
          {project.configuration_system && (
            <Tooltip
              value="Configuration System"
              arrowPosition="right"
              className="ml-6">
              <Badge color="red">
                <Icon
                  icon={project.configuration_system_icon}
                  className="mr-1"
                />
                {project.configuration_system}
              </Badge>
            </Tooltip>
          )}
          {project.data_center && (
            <Tooltip value="Data Center" arrowPosition="right">
              <Badge color="purple" href="#" target="_new">
                <Icon icon={project.data_center_icon} className="mr-1" />
                {project.data_center}
              </Badge>
            </Tooltip>
          )}
        </div>
      </div>
      <div className="my-2 flex flex-row">
        <div className="flex-1 text-gray-500 mx-3">
          <span className="mr-2">{t('terms.links')}:</span>
          <IconBar icons={project.links} />
        </div>
        <div className="flex-1 space-x-2 text-right">
          {project.environments &&
            project.environments.map((environment) => {
              return (
                <Badge color="gray" key={`environment-${environment}`}>
                  <Icon icon="fas external-link-alt" className="mr-2" />
                  {environment}
                </Badge>
              )
            })}
        </div>
      </div>
      <p className="m-3 text-sm text-gray-500">{project.description}</p>
      <div className="my-4 bg-white px-4 py-2 border-b border-gray-200 rounded-md">
        <div className="border-b border-gray-200 mb-4">
          <nav className="-mb-px flex space-x-8" aria-label="Tabs">
            <a
              href="#"
              className="border-indigo-500 text-blue-700 whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm">
              Overview
            </a>
            <a
              href="#"
              className="border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm">
              Logs
            </a>
            <a
              href="#"
              className="border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm">
              Operational Log
            </a>
            <a
              href="#"
              className="border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm">
              Configuration
            </a>
            <a
              href="#"
              className="border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm">
              Dependencies
            </a>
            <a
              href="#"
              className="border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm">
              History
            </a>
          </nav>
        </div>
        <div className="py-2 text-gray-400 align-center text-center">
          Tab Content
        </div>
      </div>
    </div>
  )
}

Project.propTypes = {}

export { Project }
