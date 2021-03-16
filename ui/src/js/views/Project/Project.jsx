import PropTypes from 'prop-types'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { Route, useParams } from 'react-router-dom'
import { onlyUpdateForKeys } from 'recompose'
import { useTranslation } from 'react-i18next'
import {
  buildStyles,
  CircularProgressbarWithChildren
} from 'react-circular-progressbar'
import 'react-circular-progressbar/dist/styles.css'

import { Context } from '../../state'
import { httpRequest, requestOptions, setDocumentTitle } from '../../utils'
import { Icon, IconBar, Loading, Tab, Tooltip } from '../../components'

import { Overview } from './Overview'

function ProjectPage({ project, factTypes, refresh }) {
  const [state, dispatch] = useContext(Context)
  const { t } = useTranslation()
  const baseURL = `/ui/projects/${project.id}`
  let color = '#cccccc'
  if (project.project_score >= 0) color = 'red'
  if (project.project_score > 69) color = 'gold'
  if (project.project_score > 89) color = '#00c800'

  useEffect(() => {
    if (state.breadcrumbs.length === 1)
      dispatch({
        type: 'SET_PAGE',
        payload: {
          title: t('projects.title'),
          url: new URL('/ui/projects', state.baseURL.toString())
        }
      })
    dispatch({
      type: 'SET_PAGE',
      payload: {
        title: project.name,
        url: new URL(baseURL, state.baseURL.toString())
      }
    })
  }, [])

  return (
    <div className="flex-auto px-6 py-4 space-y-3">
      <div className="flex justify-between">
        <div className="flex-shrink flex flex-col space-y-2 ml-2">
          <h1 className="text-gray-600 text-xl">
            <Icon icon={project.project_icon} className="mr-2" />
            {project.project_type}
          </h1>
          <div className="text-gray-500">
            {project.links.length === 0 && ' '}
            {project.links.length > 0 && (
              <Fragment>
                <span className="mr-2">{t('terms.links')}:</span>
                <IconBar icons={project.links} />
              </Fragment>
            )}
          </div>
        </div>
        <div
          className="flex-shrink mr-2"
          style={{ height: '60px', width: '60px' }}>
          <Tooltip
            value={t('project.projectHealthScore')}
            arrowPosition="right">
            <CircularProgressbarWithChildren
              value={project.project_score}
              styles={buildStyles({
                pathColor: color,
                trailColor: '#ccc'
              })}>
              <div className="absolute text-gray-600 font-semibold text-lg">
                {parseInt(project.project_score)}
              </div>
            </CircularProgressbarWithChildren>
          </Tooltip>
        </div>
      </div>
      <p className="text-sm ml-2 text-gray-500">{project.description}</p>
      <nav
        className="relative z-0 rounded-lg shadow flex divide-x divide-gray-200"
        aria-label="Tabs">
        <Tab to={baseURL} isFirst={true}>
          {t('common.overview')}
        </Tab>
        <Tab disabled={true} to={`${baseURL}/configuration`}>
          {t('common.configuration')}
        </Tab>
        <Tab disabled={true} to={`${baseURL}/dependencies`}>
          {t('project.dependencies')}
        </Tab>
        <Tab disabled={true} to={`${baseURL}/fact-history`}>
          {t('project.factHistory')}
        </Tab>
        <Tab disabled={true} to={`${baseURL}/logs`}>
          {t('common.logs')}
        </Tab>
        <Tab disabled={true} to={`${baseURL}/notes`}>
          {t('common.notes')}
        </Tab>
        <Tab disabled={true} to={`${baseURL}/operations-log`} isLast={true}>
          {t('operationsLog.title')}
        </Tab>
      </nav>
      <Fragment>
        <Route path={`/ui/projects/${project.id}`} exact>
          <Overview project={project} factTypes={factTypes} refresh={refresh} />
        </Route>
        <Route path={`/ui/projects/${project.id}/logs`}>
          <div>Logs</div>
        </Route>
      </Fragment>
    </div>
  )
}
ProjectPage.propTypes = {
  factTypes: PropTypes.arrayOf(PropTypes.object).isRequired,
  project: PropTypes.object.isRequired,
  refresh: PropTypes.func
}
const PureProjectPage = onlyUpdateForKeys(['errorMessage', 'project'])(
  ProjectPage
)

function Project() {
  const [globalState] = useContext(Context)
  const { projectId } = useParams()
  const [state, setState] = useState({
    errorMessage: null,
    project: null,
    factTypes: null
  })
  const { t } = useTranslation()

  function loadProject() {
    const factTypeURL = new URL(
      `/projects/${projectId}/fact-types`,
      globalState.baseURL
    )
    const projectURL = new URL(`/projects/${projectId}`, globalState.baseURL)
    projectURL.searchParams.append('full', 'true')
    Promise.all([
      httpRequest(globalState.fetch, factTypeURL, requestOptions),
      httpRequest(globalState.fetch, projectURL, requestOptions)
    ]).then(([factTypes, project]) => {
      const newState = { ...state, errorMessage: null }
      if (factTypes.success) newState.factTypes = factTypes.data
      else newState.errorMessage = factTypes.data
      if (project.success) newState.project = project.data
      else newState.errorMessage = project.data
      setState(newState)
      window.scrollTo(0, 0)
    })
  }

  useEffect(() => {
    if (state.project === null) loadProject()
  }, [projectId, state])

  if (state.project === null) {
    setDocumentTitle(t('common.loading'))
    return <Loading />
  } else
    return (
      <PureProjectPage
        errorMessage={state.errorMessage}
        factTypes={state.factTypes}
        project={state.project}
        refresh={loadProject}
      />
    )
}
Project.propTypes = {}
export { Project }
