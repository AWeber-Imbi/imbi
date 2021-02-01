import PropTypes from 'prop-types'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { validate } from 'jsonschema'
import { default as slugify } from 'slugify'

import { Alert, Button, Field, Icon } from '../../components'
import { FetchContext } from '../../contexts'
import { fetchMetadata } from './metadata'
import { jsonSchema } from '../../schema/Project'
import { User } from '../../schema'
import { httpPost } from '../../utils'

function NewProject() {
  const { t } = useTranslation()
  const emptyErrors = {
    namespace_id: null,
    project_type_id: null,
    name: null,
    slug: null,
    description: null,
    data_center: null,
    environments: null,
    configuration_system: null,
    deployment_type: null,
    orchestration_system: null
  }
  const [errors, setErrors] = useState(emptyErrors)
  const [errorMessage, setErrorMessage] = useState(null)
  const fetchMethod = useContext(FetchContext)
  const [formReady, setFormReady] = useState(false)
  const [metadata, setMetadata] = useState({
    configurationSystems: null,
    cookieCutters: null,
    dataCenters: null,
    deploymentTypes: null,
    environments: null,
    namespaces: null,
    orchestrationSystems: null,
    projectLinkTypes: null,
    projectTypes: null,
    ready: false
  })
  const [projectId, setProjectId] = useState(null)
  const [saving, setSaving] = useState(false)
  const [formValues, setFormValues] = useState({
    namespace_id: null,
    project_type_id: null,
    name: null,
    slug: null,
    description: null,
    data_center: null,
    environments: null,
    configuration_system: null,
    deployment_type: null,
    orchestration_system: null
  })

  async function handleSubmit(event) {
    event.preventDefault()
    setSaving(true)
    let result = await httpPost(fetchMethod, '/projects', formValues)
    if (result.success === true) {
      setProjectId(result.data.id)
      console.log(result.data)
      console.log('Project Saved')
    } else {
      setErrorMessage(result.data)
    }
  }

  function onValueChange(key, value) {
    const values = { ...formValues, [key]: value }
    console.log('Changing ' + key + ' to ' + value)
    if (key === 'name') values.slug = slugify(value).toLowerCase()
    setFormValues(values)
  }

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
      console.log(result.errors)
      setErrors(errors)
      setFormReady(false)
    } else {
      setErrors({ ...emptyErrors })
      setFormReady(true)
    }
  }, [formValues])

  useEffect(() => {
    if (metadata.ready !== true)
      fetchMetadata(fetchMethod, setMetadata, setErrorMessage)
  }, [metadata])

  return (
    <div className="flex-grow flex flex-row px-6 py-4 w-full">
      <div className="flex-shrink pr-20 text-gray-600">
        <h1 className="inline-block text-xl mb-3">
          <Icon icon="fas folder-plus" className="mr-2" />
          {t('projects.newProject')}
        </h1>
        <ol className="list-decimal list-inside ml-4 text-gray-500">
          <li className="mb-2">
            <a className="text-gray-600 hover:text-blue-600" href="#attributes">
              Attributes
            </a>
          </li>
          <li className="mb-2">
            <a className="text-gray-600 hover:text-blue-600" href="#links">
              Links
            </a>
          </li>
        </ol>
      </div>
      <div className="flex-auto bg-white max-w-screen-lg p-5 rounded-lg text-gray-700">
        {errorMessage !== null && (
          <Alert className="mb-3" level="error">
            {errorMessage}
          </Alert>
        )}
        <form onSubmit={handleSubmit}>
          <div className="pb-5">
            <h3 className="text-lg leading-6 font-medium">
              <a name="attributes">Project Attributes</a>
            </h3>
          </div>
          <div className="border-t border-gray-300 w-full pl-5">
            <Field
              title={t('project.namespace')}
              name="namespace_id"
              type="select"
              autoFocus={true}
              castTo='number'
              options={metadata.namespaces !== null ? metadata.namespaces : []}
              onChange={onValueChange}
              errorMessage={errors.namespace_id}
              required={true}
            />
            <Field
              title={t('project.name')}
              name="name"
              type="text"
              errorMessage={errors.name}
              onChange={onValueChange}
              required={true}
            />
            <Field
              title={t('project.projectType')}
              name="project_type_id"
              type="select"
              castTo='number'
              options={
                metadata.projectTypes !== null ? metadata.projectTypes : []
              }
              onChange={onValueChange}
              errorMessage={errors.project_type_id}
              required={true}
            />
            <Field
              title={t('common.slug')}
              name="slug"
              type="text"
              description={t('common.slugDescription')}
              errorMessage={errors.slug}
              onChange={onValueChange}
              required={true}
              value={formValues.slug}
            />
            <Field
              title={t('common.description')}
              name="description"
              description={t(
                'Provide a high-level purpose and context for the project'
              )}
              type="textarea"
              onChange={onValueChange}
              errorMessage={errors.description}
            />
            <Field
              title={t('project.dataCenter')}
              name="data_center"
              type="select"
              options={
                metadata.dataCenters !== null ? metadata.dataCenters : []
              }
              onChange={onValueChange}
              errorMessage={errors.data_center}
            />
            <Field
              title={t('project.environments')}
              name="environments"
              type="select"
              multiple={true}
              options={
                metadata.environments !== null ? metadata.environments : []
              }
              onChange={onValueChange}
              errorMessage={errors.environments}
            />
            <Field
              title={t('project.configurationSystem')}
              name="configuration_system"
              type="select"
              options={
                metadata.configurationSystems !== null
                  ? metadata.configurationSystems
                  : []
              }
              onChange={onValueChange}
              errorMessage={errors.configuration_system}
            />
            <Field
              title={t('project.deploymentType')}
              name="deployment_type"
              type="select"
              options={
                metadata.deploymentTypes !== null
                  ? metadata.deploymentTypes
                  : []
              }
              onChange={onValueChange}
              errorMessage={errors.deployment_type}
            />
            <Field
              title={t('project.orchestrationSystem')}
              name="orchestration_system"
              type="select"
              options={
                metadata.orchestrationSystems !== null
                  ? metadata.orchestrationSystems
                  : []
              }
              onChange={onValueChange}
              errorMessage={errors.orchestration_system}
            />
          </div>

          <div className="pt-10 pb-5">
            <h3 className="text-lg leading-6 font-medium text-gray-700">
              <a name="links">Project Links</a>
            </h3>
          </div>
          <div className="border-t border-gray-300 w-full pl-5">
            {metadata.projectLinkTypes !== null &&
              metadata.projectLinkTypes.map((linkType) => {
                const key = 'link-' + linkType.link_type
                const title = (
                  <Fragment>
                    <Icon className="mr-2" icon={linkType.icon_class} />
                    {linkType.link_type}
                  </Fragment>
                )
                return <Field title={title} key={key} name={key} type="text" />
              })}
          </div>

          <div className="flex flex-row border-t border-gray-300 mt-5 pt-5">
            <div className="flex-shrink text-xs pl-2">
              <sup className="mr-2">*</sup> {t('common.required')}
            </div>
            <div className="flex-grow text-right space-x-3">
              <Button
                className="btn-green"
                disabled={formReady !== true}
                type="submit">
                {saving ? t('common.saving') : t('common.save')}
              </Button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}

NewProject.propTypes = {
  user: PropTypes.exact(User)
}

export { NewProject }
