import { compare } from 'fast-json-patch'
import PropTypes from 'prop-types'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { default as slugify } from 'slugify'
import { useTranslation } from 'react-i18next'

import { asOptions } from '../../metadata'
import { Card, ErrorBoundary, Form, Icon } from '../../components'
import { Context } from '../../state'
import { jsonSchema } from '../../schema/Project'
import { httpDelete, httpPost, httpPatch } from '../../utils'

async function saveLinkChanges(globalState, project, originalLinks, links) {
  const errors = []
  const ops = {
    add: [],
    delete: [],
    update: []
  }
  // Build arrays of operations for syncing individual records
  Object.entries(links).forEach(([key, url]) => {
    const linkTypeID = parseInt(key)
    if (url.trim() === '' && originalLinks[linkTypeID] !== undefined) {
      ops.delete.push(linkTypeID)
    } else if (url.trim() !== '' && originalLinks[linkTypeID] === undefined) {
      ops.add.push({
        project_id: project.id,
        link_type_id: linkTypeID,
        url: url.trim()
      })
    } else if (url.trim() !== '' && originalLinks[linkTypeID] !== url.trim()) {
      ops.update.push([
        linkTypeID,
        compare(
          {
            project_id: project.id,
            link_type_id: linkTypeID,
            url: originalLinks[linkTypeID]
          },
          {
            project_id: project.id,
            link_type_id: linkTypeID,
            url: url.trim()
          }
        )
      ])
    }
  })

  const linkURL = new URL(`/projects/${project.id}/links`, globalState.baseURL)
  for (let payload of ops.add) {
    const result = await httpPost(globalState.fetch, linkURL, payload)
    if (result.success === false) {
      errors.push(result.data)
    }
  }

  let linkTypeID
  for (linkTypeID of ops.delete) {
    linkURL.pathname = `/projects/${project.id}/links/${linkTypeID}`
    const result = await httpDelete(globalState.fetch, linkURL)
    if (result.success === false) {
      errors.push(result.data)
    }
  }

  let patch
  for (patch of ops.update) {
    linkURL.pathname = `/projects/${project.id}/links/${patch[0]}`
    const result = await httpPatch(globalState.fetch, linkURL, patch[1])
    if (result.success === false) {
      errors.push(result.data)
    }
  }
  return [errors.length === 0, errors]
}

async function saveProjectChanges(globalState, project, values) {
  const originalValues = {
    name: project.name,
    namespace_id: project.namespace_id,
    project_type_id: project.project_type_id,
    slug: project.slug,
    description: project.description,
    environments: project.environments
  }
  const patchValue = compare(originalValues, values)
  if (patchValue.length > 0) {
    const projectURL = new URL(`/projects/${project.id}`, globalState.baseURL)
    const result = await httpPatch(globalState.fetch, projectURL, patchValue)
    if (result.success === false) {
      return [false, result.data]
    }
  }
  return [true, null]
}

async function saveURLChanges(globalState, project, environments, urls) {
  const errors = []
  const ops = {
    add: [],
    delete: [],
    update: []
  }
  // Build arrays of operations for syncing individual records
  Object.entries(urls).forEach(([key, url]) => {
    if (url.trim() === '' && project.urls[key] !== undefined) {
      ops.delete.push(key)
    } else if (project.urls[key] === undefined) {
      ops.add.push({
        project_id: project.id,
        environment: key,
        url: url.trim()
      })
    } else if (project.urls[key] !== url.trim()) {
      ops.update.push([
        key,
        compare(
          {
            project_id: project.id,
            environment: key,
            url: project.urls[key]
          },
          {
            project_id: project.id,
            environment: key,
            url: url.trim()
          }
        )
      ])
    } else if (!environments.includes(key)) {
      ops.delete.push(key)
    }
  })

  const projectURL = new URL(
    `/projects/${project.id}/urls`,
    globalState.baseURL
  )
  for (let payload of ops.add) {
    const result = await httpPost(globalState.fetch, projectURL, payload)
    if (result.success === false) {
      errors.push(result.data)
    }
  }

  for (let environment of ops.delete) {
    projectURL.pathname = `/projects/${project.id}/urls/${environment}`
    const result = await httpDelete(globalState.fetch, projectURL)
    if (result.success === false) {
      errors.push(result.data)
    }
  }

  for (let patch of ops.update) {
    projectURL.pathname = `/projects/${project.id}/urls/${patch[0]}`
    const result = await httpPatch(globalState.fetch, projectURL, patch[1])
    if (result.success === false) {
      errors.push(result.data)
    }
  }
  return [errors.length === 0, errors]
}

function Edit({ project, onEditFinished }) {
  const emptyErrors = {
    namespace_id: null,
    project_type_id: null,
    name: null,
    slug: null,
    description: null,
    environments: null
  }
  const [globalState] = useContext(Context)
  const environmentIcons = Object.fromEntries(
    globalState.metadata.environments.map((environment) => [
      environment.name,
      environment.icon_class
    ])
  )

  const originalLinks = Object.fromEntries(
    project.links.map((link) => [link.link_type_id, link.url])
  )

  const [state, setState] = useState({
    errorMessage: null,
    projectErrors: emptyErrors,
    projectReady: false,
    linkErrors: {},
    linksReady: false,
    saveComplete: false,
    saving: false,
    values: {
      namespace_id: project.namespace_id,
      project_type_id: project.project_type_id,
      name: project.name,
      slug: project.slug,
      description: project.description,
      environments: project.environments
    },
    links: originalLinks,
    urlErrors: {},
    urls: project.urls,
    urlsReady: false
  })
  const { t } = useTranslation()

  useEffect(() => {
    const [linksReady, lErrors] = Form.validateURLs(state.links)
    const linkErrors = Object.fromEntries(
      lErrors.map((id) => [id, t('common.invalidURL')])
    )
    const [urlsReady, uErrors] = Form.validateURLs(state.urls)
    const urlErrors = Object.fromEntries(
      uErrors.map((environment) => [environment, t('common.invalidURL')])
    )
    const [projectReady, projectErrors] = Form.validateObject(
      state.values,
      jsonSchema
    )
    setState({
      ...state,
      linkErrors: linkErrors,
      linksReady: linksReady,
      projectErrors: { ...emptyErrors, ...projectErrors },
      projectReady: projectReady,
      urlErrors: urlErrors,
      urlsReady: urlsReady
    })
  }, [state.links, state.urls, state.values])

  useEffect(() => {
    if (state.saveComplete === true) {
      onEditFinished(true)
    }
  }, [state.saveComplete])

  function onLinkChange(key, value) {
    const linkKey = parseInt(key.split('-')[1])
    if (state.links[linkKey] !== value)
      setState({ ...state, links: { ...state.links, [linkKey]: value } })
  }

  function onURLChange(key, value) {
    const urlKey = key.split('-')[1]
    if (state.urls[urlKey] !== value)
      setState({ ...state, urls: { ...state.urls, [urlKey]: value } })
  }

  function onValueChange(key, value) {
    const values = { ...state.values, [key]: value }
    if (state.values[key] !== value) {
      if (key === 'name' && values.slug === '')
        values.slug = slugify(value).toLowerCase()
      setState({ ...state, values: values })
    }
  }

  async function onSubmit() {
    setState({ ...state, saving: true })
    const [projectResult, projectErrorMessage] = await saveProjectChanges(
      globalState,
      project,
      state.values
    )
    if (!projectResult) {
      setState({ ...state, errorMessage: projectErrorMessage, saving: false })
      return
    }
    const [linksResult, linksErrors] = await saveLinkChanges(
      globalState,
      project,
      originalLinks,
      state.links
    )
    if (!linksResult) {
      console.log(linksErrors)
      setState({ ...state, errorMessage: 'Error saving links', saving: false })
      return
    }
    const [urlsResult, urlsErrors] = await saveURLChanges(
      globalState,
      project,
      state.values.environments,
      state.urls
    )
    if (!urlsResult) {
      console.error(urlsErrors)
      setState({ ...state, errorMessage: 'Error saving URLS', saving: false })
      return
    }
    setState({ ...state, saving: false, saveComplete: true })
  }

  return (
    <ErrorBoundary>
      <Card className="flex flex-col h-full">
        <h2 className="font-medium mb-2">{t('project.editInfo')}</h2>
        <Form.SimpleForm
          errorMessage={state.errorMessage}
          onCancel={onEditFinished}
          onSubmit={onSubmit}
          ready={state.linksReady && state.projectReady && state.urlsReady}
          saving={state.saving}>
          <Form.Field
            title={t('project.namespace')}
            name="namespace_id"
            type="select"
            autoFocus={true}
            castTo="number"
            options={asOptions(globalState.metadata.namespaces)}
            onChange={onValueChange}
            errorMessage={state.projectErrors.namespace_id}
            required={true}
            value={state.values.namespace_id}
          />
          <Form.Field
            title={t('project.projectType')}
            name="project_type_id"
            type="select"
            castTo="number"
            options={asOptions(globalState.metadata.projectTypes)}
            onChange={onValueChange}
            errorMessage={state.projectErrors.project_type_id}
            required={true}
            value={state.values.project_type_id}
          />
          <Form.Field
            title={t('project.name')}
            name="name"
            type="text"
            errorMessage={state.projectErrors.name}
            onChange={onValueChange}
            required={true}
            value={state.values.name}
          />
          <Form.Field
            title={t('common.slug')}
            name="slug"
            type="text"
            description={t('common.slugDescription')}
            errorMessage={state.projectErrors.slug}
            onChange={onValueChange}
            required={true}
            value={state.values.slug}
          />
          <Form.Field
            title={t('common.description')}
            name="description"
            description={t('project.descriptionDescription')}
            type="textarea"
            onChange={onValueChange}
            errorMessage={state.projectErrors.description}
            value={state.values.description}
          />
          <Form.Field
            title={t('project.environments')}
            name="environments"
            type="select"
            multiple={true}
            options={asOptions(
              globalState.metadata.environments,
              'name',
              'name'
            )}
            onChange={onValueChange}
            errorMessage={state.projectErrors.environments}
            value={state.values.environments}
          />
          {state.values.environments !== null &&
            state.values.environments.map((environment) => {
              return (
                <Form.Field
                  title={
                    <Fragment>
                      <Icon
                        className="mr-2"
                        icon={environmentIcons[environment]}
                      />
                      {environment} URL
                    </Fragment>
                  }
                  name={`url-${environment}`}
                  key={`url-${environment}`}
                  type="text"
                  errorMessage={state.urlErrors[environment]}
                  onChange={onURLChange}
                  value={
                    state.urls[environment] !== undefined
                      ? state.urls[environment]
                      : ''
                  }
                />
              )
            })}
          {globalState.metadata.projectLinkTypes.map((linkType) => {
            return (
              <Form.Field
                title={
                  <Fragment>
                    <Icon className="mr-2" icon={linkType.icon_class} />
                    {linkType.link_type} URL
                  </Fragment>
                }
                key={`link-${linkType.id}`}
                name={`link-${linkType.id}`}
                type="url"
                onChange={onLinkChange}
                errorMessage={state.linkErrors[linkType.id]}
                value={
                  state.links[linkType.id] !== undefined
                    ? state.links[linkType.id]
                    : ''
                }
              />
            )
          })}
        </Form.SimpleForm>
      </Card>
    </ErrorBoundary>
  )
}
Edit.propTypes = {
  project: PropTypes.object.isRequired,
  onEditFinished: PropTypes.func.isRequired
}
export { Edit }
