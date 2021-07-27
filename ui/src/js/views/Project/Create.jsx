import PropTypes from 'prop-types'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { default as slugify } from 'slugify'
import { useHistory } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { validate } from 'jsonschema'

import { asOptions } from '../../metadata'
import { Context } from '../../state'
import { ErrorBoundary, Form, Icon, SavingModal } from '../../components'
import { jsonSchema } from '../../schema/Project'
import { User } from '../../schema'
import { httpPost, isURL } from '../../utils'

function SideBar({ links }) {
  return (
    <ol className="list-decimal list-inside ml-4 text-gray-500 whitespace-nowrap">
      {links.map((link) => {
        return (
          <li className="mb-2" key={'link-' + link.label}>
            <a className="text-gray-600 hover:text-blue-600" href={link.href}>
              {link.label}
            </a>
          </li>
        )
      })}
    </ol>
  )
}
SideBar.propTypes = {
  links: PropTypes.arrayOf(
    PropTypes.exact({
      href: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired
    })
  )
}

function Create() {
  const [automations, setAutomations] = useState({
    createGitlabRepo: false,
    createSonarProject: false,
    createSentryProject: false,
    dashboardCookieCutter: null,
    projectCookieCutter: null
  })
  const emptyErrors = {
    namespace_id: null,
    project_type_id: null,
    name: null,
    slug: null,
    description: null,
    environments: null
  }
  const [errors, setErrors] = useState(emptyErrors)
  const [errorMessage, setErrorMessage] = useState(null)
  const [links, setLinks] = useState({})
  const [formReady, setFormReady] = useState(false)
  const [formValues, setFormValues] = useState({
    namespace_id: null,
    project_type_id: null,
    name: null,
    slug: null,
    description: null,
    environments: null
  })
  const history = useHistory()
  const [projectId, setProjectId] = useState(null)
  const [saveComplete, setSaveComplete] = useState({
    attributes: false,
    gitlabRepo: false,
    sonarProject: false,
    gitlabCommit: false,
    links: false,
    urls: false
  })
  const [saving, setSaving] = useState(false)
  const [savingSteps, setSavingSteps] = useState([])
  const [state, dispatch] = useContext(Context)
  const [urls, setURLs] = useState([])
  const { t } = useTranslation()
  const [gitlabEnabled, setGitlabEnabled] = useState(false)

  // Only want to make the gitlab automation available if the project type
  // has a configured project prefix
  const gitlabEnabledNamespaces = (state.metadata.namespaces || [])
    .filter((namespace) => namespace.gitlab_group_name !== null)
    .map((namespace) => namespace.id)
  const gitlabEnabledTypes = (state.metadata.projectTypes || [])
    .filter((projectType) => projectType.gitlab_project_prefix !== null)
    .map((projectType) => projectType.id)

  function onAutomationChange(key, value) {
    setAutomations({ ...automations, [key]: value })
    // Set URls based upon key changes
  }

  function onLinkChange(key, value) {
    const linkType = parseInt(key.split('-')[1])
    if (value === '') {
      const newLinks = { ...links }
      if (newLinks[linkType] !== undefined) delete newLinks[linkType]
      setLinks(newLinks)
      setErrors({ ...errors, [key]: null })
    } else {
      if (isURL(value) === true) {
        setErrors({ ...errors, [key]: null })
        setLinks({ ...links, [linkType]: value })
      } else {
        setErrors({ ...errors, [key]: t('common.invalidURL') })
      }
    }
  }

  function onURLChange(key, value) {
    const environment = key.split('-')[1]
    if (value === '') {
      const newURLs = { ...urls }
      if (newURLs[environment] !== undefined) delete newURLs[environment]
      setURLs(newURLs)
      setErrors({ ...errors, [`url-${environment}`]: null })
    } else {
      if (isURL(value) === true) {
        setErrors({ ...errors, [`url-${environment}`]: null })
        setURLs({ ...urls, [environment]: value })
      } else {
        setErrors({ ...errors, [`url-${environment}`]: t('common.invalidURL') })
      }
    }
  }

  function onValueChange(key, value) {
    const values = { ...formValues, [key]: value }
    if (key === 'name') values.slug = slugify(value).toLowerCase()
    setFormValues(values)
  }

  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'projects.newProject',
        url: new URL('/ui/projects/create', state.baseURL)
      }
    })
  }, [])

  // Save Project, Links, Dependencies, and Perform Automations
  useEffect(() => {
    async function saveProject() {
      if (saving === true) {
        if (saveComplete.attributes === false) {
          let result = await httpPost(
            state.fetch,
            new URL('/projects', state.baseURL),
            formValues
          )
          if (result.success === true) {
            setSaveComplete({ ...saveComplete, attributes: true })
            setProjectId(result.data.id)
          } else {
            setErrorMessage(result.data)
            setSaving(false)
          }
        } else if (saveComplete.gitlabRepo === false && projectId !== null) {
          if (automations.createGitlabRepo && gitlabEnabled) {
            let result = await httpPost(
              state.fetch,
              new URL('/ui/automations/gitlab/create', state.baseURL),
              {
                description: formValues.description,
                name: formValues.name,
                project_id: projectId
              }
            )
            if (result.success === true) {
              // order is important here ... no need to make this effect depend on automations as well
              setAutomations({
                ...automations,
                createSonarProject: result.data.create_sonar_project
              })
              setSaveComplete({ ...saveComplete, gitlabRepo: true })
            } else {
              setErrorMessage(result.data)
              setSaving(false)
            }
          } else {
            setSaveComplete({ ...saveComplete, gitlabRepo: true })
          }
        } else if (
          saveComplete.gitlabRepo !== false &&
          saveComplete.sonarProject === false
        ) {
          if (automations.createSonarProject) {
            let result = await httpPost(
              state.fetch,
              new URL('/ui/automations/sonar/create', state.baseURL),
              { project_id: projectId }
            )
            if (result.success === true) {
              setSaveComplete({ ...saveComplete, sonarProject: true })
            } else {
              setErrorMessage(result.data)
            }
          } else {
            setSaveComplete({ ...saveComplete, sonarProject: true })
          }
        } else if (
          saveComplete.gitlabCommit === false &&
          saveComplete.gitlabRepo !== false
        ) {
          if (automations.projectCookieCutter && gitlabEnabled) {
            let result = await httpPost(
              state.fetch,
              new URL('/ui/automations/gitlab/commit', state.baseURL),
              {
                cookie_cutter: automations.projectCookieCutter,
                project_id: projectId
              }
            )
            if (result.success === true) {
              setSaveComplete({ ...saveComplete, gitlabCommit: true })
            } else {
              setErrorMessage(result.data)
              setSaving(false)
            }
          } else {
            setSaveComplete({ ...saveComplete, gitlabCommit: true })
          }
        } else if (saveComplete.urls === false && projectId !== null) {
          if (Object.values(urls).length > 0) {
            for (const [environment, url] of Object.entries(urls)) {
              let result = await httpPost(
                state.fetch,
                new URL(
                  '/projects/' + projectId.toString() + '/urls',
                  state.baseURL
                ),
                {
                  project_id: projectId,
                  environment: environment,
                  url: url
                }
              )
              if (result.success === false) {
                setErrorMessage(result.data)
                setSaving(false)
                return
              }
            }
            setSaveComplete({ ...saveComplete, urls: true })
          } else {
            setSaveComplete({ ...saveComplete, urls: true })
          }
        } else if (saveComplete.links === false && projectId !== null) {
          if (Object.values(links).length > 0) {
            for (const [linkTypeId, url] of Object.entries(links)) {
              let result = await httpPost(
                state.fetch,
                new URL(
                  '/projects/' + projectId.toString() + '/links',
                  state.baseURL
                ),
                {
                  project_id: projectId,
                  link_type_id: parseInt(linkTypeId),
                  url: url
                }
              )
              if (result.success === false) {
                setErrorMessage(result.data)
                setSaving(false)
                return
              }
              setSaveComplete({ ...saveComplete, links: true })
            }
          } else {
            setSaveComplete({ ...saveComplete, links: true })
          }
        }
      }
    }
    saveProject()
  }, [projectId, saving, saveComplete])

  // Validate form values as they change
  useEffect(() => {
    const result = validate(formValues, jsonSchema)
    if (result.errors.length > 0) {
      const errors = { ...emptyErrors }
      result.errors.map((err) => {
        err.path.map((field) => {
          if (formValues[field] !== null) {
            errors[field] = err.message
          }
        })
      })
      setErrors(errors)
      setFormReady(false)
    } else {
      setErrors({ ...emptyErrors })
      setFormReady(true)
    }
  }, [formValues])

  // Update the available steps when saving for the UI
  useEffect(() => {
    const steps = [
      {
        isComplete: saveComplete.attributes,
        pendingLabel: t('project.savingProject'),
        completedLabel: t('project.projectSaved')
      }
    ]
    if (Object.values(urls).length > 0) {
      steps.push({
        isComplete: saveComplete.urls,
        pendingLabel: t('project.savingURLs'),
        completedLabel: t('project.urlsSaved')
      })
    }
    if (Object.values(links).length > 0) {
      steps.push({
        isComplete: saveComplete.links,
        pendingLabel: t('project.savingLinks'),
        completedLabel: t('project.linksSaved')
      })
    }
    if (automations.createGitlabRepo === true && gitlabEnabled) {
      steps.push({
        isComplete: saveComplete.gitlabRepo,
        pendingLabel: t('project.gitlab.creatingRepo'),
        completedLabel: t('project.gitlab.repoCreated')
      })
    }
    if (automations.createSentryProject === true) {
      steps.push({
        isComplete: false,
        pendingLabel: t('project.createSentryProject'),
        completedLabel: t('project.sentryProjectCreated')
      })
    }
    if (automations.projectCookieCutter !== null) {
      steps.push({
        isComplete: saveComplete.gitlabCommit,
        pendingLabel: t('project.gitlab.creatingInitialCommit'),
        completedLabel: t('project.gitlab.initialCommitCreated')
      })
    }
    if (automations.dashboardCookieCutter !== null) {
      steps.push({
        isComplete: false,
        pendingLabel: t('project.creatingGrafanaDashboard'),
        completedLabel: t('project.grafanaDashboardCreated')
      })
    }
    setSavingSteps(steps)
  }, [saveComplete, links, automations, gitlabEnabled])

  // Update UI elements when changing the project type or namespace
  useEffect(() => {
    const { namespace_id, project_type_id } = formValues
    setGitlabEnabled(
      gitlabEnabledNamespaces.includes(namespace_id) &&
        gitlabEnabledTypes.includes(project_type_id)
    )
  }, [formValues])

  return (
    <ErrorBoundary>
      <Form.MultiSectionForm
        disabled={!formReady}
        icon="fas file"
        instructions={
          <div className="ml-2 text-sm">* {t('common.required')}</div>
        }
        errorMessage={errorMessage}
        sideBarLinks={[
          { href: '#attributes', label: t('project.attributes') },
          { href: '#urls', label: t('project.urls') },
          { href: '#automations', label: t('project.automations') },
          { href: '#links', label: t('project.links') }
        ]}
        sideBarTitle={t('projects.newProject')}
        onSubmit={(event) => {
          event.preventDefault()
          setSaving(true)
        }}
        submitButtonText={saving ? t('common.saving') : t('common.save')}>
        <Form.Section
          name="attributes"
          title={t('project.projectAttributes')}
          firstSection={true}>
          <Form.Field
            title={t('project.namespace')}
            name="namespace_id"
            type="select"
            autoFocus={true}
            castTo="number"
            options={asOptions(state.metadata.namespaces)}
            onChange={onValueChange}
            errorMessage={errors.namespace_id}
            required={true}
          />
          <Form.Field
            title={t('project.projectType')}
            name="project_type_id"
            type="select"
            castTo="number"
            options={asOptions(state.metadata.projectTypes)}
            onChange={onValueChange}
            errorMessage={errors.project_type_id}
            required={true}
          />
          <Form.Field
            title={t('project.name')}
            name="name"
            type="text"
            errorMessage={errors.name}
            onChange={onValueChange}
            required={true}
          />
          <Form.Field
            title={t('common.slug')}
            name="slug"
            type="text"
            description={t('common.slugDescription')}
            errorMessage={errors.slug}
            onChange={onValueChange}
            required={true}
            value={formValues.slug}
          />
          <Form.Field
            title={t('common.description')}
            name="description"
            description={t('project.descriptionDescription')}
            type="textarea"
            onChange={onValueChange}
            errorMessage={errors.description}
          />
          <Form.Field
            title={t('project.environments')}
            name="environments"
            type="select"
            multiple={true}
            options={asOptions(state.metadata.environments, 'name', 'name')}
            onChange={onValueChange}
            errorMessage={errors.environments}
          />
        </Form.Section>
        <Form.Section name="urls" title={t('project.projectURLs')}>
          <Fragment>
            {(formValues.environments === null ||
              formValues.environments.length === 0) && (
              <p className="text-center p-6 font-mono">
                {t('project.specifyEnvironments')}
              </p>
            )}
            {formValues.environments !== null &&
              formValues.environments.map((environment) => {
                return (
                  <Form.Field
                    title={`${environment} URL`}
                    name={`url-${environment}`}
                    key={`url-${environment}`}
                    type="text"
                    errorMessage={errors[`url-${environment}`]}
                    onChange={onURLChange}
                  />
                )
              })}
          </Fragment>
        </Form.Section>
        <Form.Section
          name="automations"
          title={t('project.projectAutomations')}>
          <Form.Field
            title={t('project.createGitLabRepository')}
            name="createGitlabRepo"
            type="toggle"
            disabled={!gitlabEnabled}
            onChange={onAutomationChange}
          />
          <Form.Field
            title={t('project.createSentryProject')}
            name="createSentryProject"
            type="toggle"
            disabled={true}
            onChange={onAutomationChange}
          />
          <Form.Field
            title={t('project.projectCookieCutter')}
            name="projectCookieCutter"
            type="select"
            disabled={!gitlabEnabled}
            options={
              state.metadata.cookieCutters !== null
                ? state.metadata.cookieCutters
                    .filter(
                      (cookieCutter) =>
                        cookieCutter.type === 'project' &&
                        cookieCutter.project_type_id ===
                          formValues.project_type_id
                    )
                    .map((cookieCutter) => {
                      return {
                        label: cookieCutter.name,
                        value: cookieCutter.url
                      }
                    })
                : []
            }
            onChange={onAutomationChange}
          />
          <Form.Field
            title={t('project.dashboardCookieCutter')}
            name="dashboardCookieCutter"
            type="select"
            disabled={true}
            options={
              state.metadata.cookieCutters !== null
                ? state.metadata.cookieCutters
                    .filter(
                      (cookieCutter) =>
                        cookieCutter.type === 'dashboard' &&
                        cookieCutter.project_type_id ===
                          formValues.project_type_id
                    )
                    .map((cookieCutter) => {
                      return {
                        label: cookieCutter.name,
                        value: cookieCutter.url
                      }
                    })
                : []
            }
            onChange={onAutomationChange}
          />
        </Form.Section>
        <Form.Section name="links" title={t('project.projectLinks')}>
          {state.metadata.projectLinkTypes.map((linkType) => {
            const key = 'link-' + linkType.id
            return (
              <Form.Field
                title={
                  <Fragment>
                    <Icon className="mr-2" icon={linkType.icon_class} />
                    {linkType.link_type}
                  </Fragment>
                }
                key={key}
                name={key}
                type="url"
                onChange={onLinkChange}
                errorMessage={errors[key]}
              />
            )
          })}
        </Form.Section>
      </Form.MultiSectionForm>
      {saving && (
        <SavingModal
          title={
            saving ? t('project.savingProject') : t('project.projectSaved')
          }
          steps={savingSteps}
          onSaveComplete={(event) => {
            event.preventDefault()
            history.push(`/ui/projects/${projectId}`)
          }}
        />
      )}
    </ErrorBoundary>
  )
}

Create.propTypes = {
  user: PropTypes.exact(User)
}

export { Create }
