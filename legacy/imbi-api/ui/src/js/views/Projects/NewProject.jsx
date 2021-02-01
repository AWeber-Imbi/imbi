import PropTypes from 'prop-types'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { default as slugify } from 'slugify'
import { useHistory } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { validate } from 'jsonschema'

import { Alert, Button, Field, Icon, SavingModal } from '../../components'
import { FetchContext } from '../../contexts'
import { fetchMetadata } from './metadata'
import { jsonSchema } from '../../schema/Project'
import { User } from '../../schema'
import { httpPost, isURL } from '../../utils'

function FormSection({ name, title, firstSection, children }) {
  return (
    <Fragment>
      <div className={'pb-5' + (firstSection ? '' : ' mt-5')}>
        <h3 className="text-lg leading-6 font-medium">
          <a name={name}>{title}</a>
        </h3>
      </div>
      <div className="border-t border-gray-300 w-full pl-5">{children}</div>
    </Fragment>
  )
}
FormSection.defaultProps = {
  firstSection: false
}
FormSection.propTypes = {
  name: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  firstSection: PropTypes.bool,
  children: PropTypes.arrayOf(PropTypes.element)
}

function SideBar({ links }) {
  return (
    <ol className="list-decimal list-inside ml-4 text-gray-500">
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
  const [links, setLinks] = useState({})
  const fetchMethod = useContext(FetchContext)
  const [formReady, setFormReady] = useState(false)
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
  const history = useHistory()
  const [metadata, setMetadata] = useState({
    configurationSystems: null,
    cookieCutters: null,
    dataCenters: null,
    deploymentTypes: null,
    environments: null,
    namespaces: null,
    orchestrationSystems: null,
    projectLinkTypes: [],
    projectTypes: null,
    ready: false
  })
  const [projectId, setProjectId] = useState(null)
  const [saveComplete, setSaveComplete] = useState({
    attributes: false,
    links: false,
    dependencies: true
  })
  const [saving, setSaving] = useState(false)

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

  function onValueChange(key, value) {
    const values = { ...formValues, [key]: value }
    if (key === 'name') values.slug = slugify(value).toLowerCase()
    setFormValues(values)
  }

  // Save Project, Links, Dependencies, and Perform Automations
  useEffect(() => {
    async function saveProject() {
      if (saving === true) {
        if (saveComplete.attributes === false) {
          let result = await httpPost(fetchMethod, '/projects', formValues)
          if (result.success === true) {
            setSaveComplete({ ...saveComplete, attributes: true })
            setProjectId(result.data.id)
          } else {
            setErrorMessage(result.data)
            setSaving(false)
          }
        } else if (saveComplete.links === false && projectId !== null) {
          for (const [linkTypeId, url] of Object.entries(links)) {
            let result = await httpPost(
              fetchMethod,
              '/projects/' + projectId.toString() + '/links',
              { project_id: projectId, link_type_id: parseInt(linkTypeId), url: url }
            )
            if (result.success === false) {
              setErrorMessage(result.data)
              setSaving(false)
              return
            }
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

  useEffect(() => {
    if (metadata.ready !== true)
      fetchMetadata(fetchMethod, setMetadata, setErrorMessage)
  }, [metadata])

  return (
    <Fragment>
      <div className="flex-grow flex flex-row px-6 py-4 w-full">
        <div className="flex-shrink pr-20 text-gray-600">
          <h1 className="inline-block text-xl mb-3">
            <Icon icon="fas folder-plus" className="mr-2" />
            {t('projects.newProject')}
          </h1>
          <SideBar
            links={[
              { href: '#attributes', label: t('project.attributes') },
              { href: '#links', label: t('project.links') }
            ]}
          />
        </div>
        <div className="flex-auto bg-white max-w-screen-lg p-5 rounded-lg text-gray-700">
          {errorMessage !== null && (
            <Alert className="mb-3" level="error">
              {errorMessage}
            </Alert>
          )}
          <form
            onSubmit={(event) => {
              event.preventDefault()
              setSaving(true)
            }}>
            <FormSection
              name="attributes"
              title={t('project.projectAttributes')}
              firstSection={true}>
              <Field
                title={t('project.namespace')}
                name="namespace_id"
                type="select"
                autoFocus={true}
                castTo="number"
                options={
                  metadata.namespaces !== null ? metadata.namespaces : []
                }
                onChange={onValueChange}
                errorMessage={errors.namespace_id}
                required={true}
              />
              <Field
                title={t('project.projectType')}
                name="project_type_id"
                type="select"
                castTo="number"
                options={
                  metadata.projectTypes !== null ? metadata.projectTypes : []
                }
                onChange={onValueChange}
                errorMessage={errors.project_type_id}
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
                description={t('project.descriptionDescription')}
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
            </FormSection>
            <FormSection name="links" title={t('project.projectLinks')}>
              {metadata.projectLinkTypes.map((linkType) => {
                const key = 'link-' + linkType.id
                return (
                  <Field
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
            </FormSection>

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
      {saving && (
        <SavingModal
          title={
            saving ? t('project.savingProject') : t('project.projectSaved')
          }
          steps={[
            {
              isComplete: saveComplete.attributes,
              pendingLabel: t('project.savingProject'),
              completedLabel: t('project.projectSaved')
            },
            {
              isComplete: saveComplete.links,
              pendingLabel: t('project.savingLinks'),
              completedLabel: t('project.linksSaved')
            },
            {
              isComplete: saveComplete.dependencies,
              pendingLabel: t('project.savingDependencies'),
              completedLabel: t('project.dependenciesSaved')
            }
          ]}
          onSaveComplete={(event) => {
            event.preventDefault()
            history.push(`/projects/${projectId}`)
          }}
        />
      )}
    </Fragment>
  )
}

NewProject.propTypes = {
  user: PropTypes.exact(User)
}

export { NewProject }
