import PropTypes from 'prop-types'
import React, { useContext, useEffect, useState } from 'react'
import { User } from '../../schema'
import { ErrorBoundary, Form } from '../../components'
import { useTranslation } from 'react-i18next'
import { asOptions } from '../../metadata'
import { Context } from '../../state'
import { httpGet, httpPatch, httpPost } from '../../utils'
import { useHistory } from 'react-router-dom'

function GitlabImport() {
  const emptyErrors = {
    gitlab_namespace_id: null,
    gitlab_project_id: null,
    namespace_id: null,
    project_type_id: null,
    top_level: null
  }
  const [errors, setErrors] = useState(emptyErrors)
  const [state] = useContext(Context)
  const history = useHistory()
  const { t } = useTranslation()
  const [formReady, setFormReady] = useState(false)
  const [formValues, setFormValues] = useState({
    gitlab_namespace_id: null,
    gitlab_project_id: null,
    namespace_id: null,
    project_type_id: null
  })
  const [formState, setFormState] = useState({
    namespaceSelected: false,
    projectName: null,
    projectDescription: null,
    projectURL: null,
    saving: false
  })
  const [namespaces, setNamespaces] = useState([])
  const [projects, setProjects] = useState([])

  function onValueChange(key, value) {
    let values = { ...formValues, [key]: value }
    if (key === 'gitlab_namespace_id') {
      values.gitlab_project_id = null
      setErrors({ ...errors, gitlab_project_id: null })
      setProjects([])
      setFormState({
        ...formState,
        namespaceSelected: false,
        projectName: null
      })
      if (value) {
        let url = new URL('/gitlab/projects', state.baseURL)
        url.searchParams.set('group_id', value)
        httpGet(
          state.fetch,
          url,
          (data) => {
            setErrors({ ...errors, [key]: null })
            if (data.length) {
              setFormState({ ...formState, namespaceSelected: true })
              setProjects(data)
            }
          },
          (error) => {
            setErrors({ ...errors, [key]: error })
          }
        )
      }
    }
    if (key === 'gitlab_project_id') {
      const projectDetails = projects.find((elm) => elm.id === value)
      if (projectDetails) {
        setFormState({
          ...formState,
          projectDescription: projectDetails.description,
          projectName: projectDetails.name,
          projectURL: projectDetails.web_url
        })
      } else {
        setFormState({ ...formState, projectName: null })
        if (value) {
          setErrors({ ...errors, [key]: 'project not found' })
        }
      }
    }
    setFormValues(values)
  }

  useEffect(() => {
    httpGet(
      state.fetch,
      new URL('/gitlab/namespaces', state.baseURL),
      (data) => {
        setNamespaces(data)
      },
      (error) => {
        setErrors({ ...errors, namespace_id: error })
      }
    )
  }, [])

  useEffect(() => {
    setErrors(emptyErrors)
    setFormReady(
      formValues.gitlab_namespace_id !== null &&
        formValues.gitlab_project_id !== null &&
        formValues.namespace_id !== null &&
        formValues.project_type_id !== null
    )
  }, [formValues])

  function importProject() {
    setFormState({ ...formState, saving: true })
    httpPost(state.fetch, new URL('/projects', state.baseURL), {
      environments: ['testing'],
      name: formState.projectName,
      namespace_id: formValues.namespace_id,
      project_type_id: formValues.project_type_id,
      slug: formState.projectName
    }).then(({ data, success }) => {
      if (success === true) {
        let projectId = data.id
        httpPatch(
          state.fetch,
          new URL(`/projects/${projectId}`, state.baseURL),
          [
            {
              op: 'replace',
              path: '/gitlab_project_id',
              value: formValues.gitlab_project_id
            }
          ]
        ).then(({ success }) => {
          if (success === true) {
            history.push(`/ui/projects/${projectId}`)
          } else {
            setErrors({ ...errors, top_level: data })
          }
          setFormState({ ...formState, saving: false })
        })
      } else {
        setErrors({ ...errors, top_level: data })
        setFormState({ ...formState, saving: false })
      }
    })
  }

  return (
    <ErrorBoundary>
      <Form.SimpleForm
        errorMessage={errors.top_level}
        ready={formReady}
        submitButtonText={t('common.import')}
        submitSavingText={t('common.importing')}
        saving={formState.saving}
        onCancel={() => {}}
        onSubmit={importProject}>
        <Form.Field
          title={t('project.gitlab.namespace')}
          name="gitlab_namespace_id"
          type="select"
          castTo="number"
          options={asOptions(namespaces)}
          onChange={onValueChange}
          errorMessage={errors.gitlab_namespace_id}
          required={true}
        />
        <Form.Field
          title={t('project.gitlab.project')}
          name="gitlab_project_id"
          type="select"
          castTo="number"
          options={asOptions(projects)}
          onChange={onValueChange}
          errorMessage={errors.gitlab_project_id}
          required={true}
          enabled={formState.namespaceSelected}
          disabled={!formState.namespaceSelected}
        />
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
      </Form.SimpleForm>
    </ErrorBoundary>
  )
}

GitlabImport.propTypes = {
  user: PropTypes.exact(User)
}

export { GitlabImport }
