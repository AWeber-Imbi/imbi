import PropTypes from 'prop-types'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Alert, Button, Field, Icon } from '../../components'
import { FetchContext } from '../../contexts'
import { fetchMetadata } from './metadata'
import { User } from '../../schema'

function NewProject() {
  const { t } = useTranslation()

  const [errors, setErrors] = useState({})
  const [errorMessage, setErrorMessage] = useState(null)
  const [formReady, setFormReady] = useState(false)
  const fetchMethod = useContext(FetchContext)
  const [metadata, setMetadata] = useState({
    configurationSystems: null,
    cookieCutters: null,
    dataCenters: null,
    deploymentTypes: null,
    environments: null,
    orchestrationSystems: null,
    projectLinkTypes: null,
    projectTypes: null,
    ready: false,
    teams: null
  })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (metadata.ready !== true)
      fetchMetadata(fetchMethod, setMetadata, setErrorMessage)
  }, [metadata])

  return (
    <div className="flex-auto flex flex-row flex-grow max-h-full px-6 py-4 w-full">
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
            <a
              className="text-gray-600 hover:text-blue-600"
              href="#automations">
              Automations
            </a>
          </li>
          <li className="mb-2">
            <a className="text-gray-600 hover:text-blue-600" href="#links">
              Links
            </a>
          </li>
          <li className="mb-2">
            <a
              className="text-gray-600 hover:text-blue-600"
              href="#dependencies">
              Dependencies
            </a>
          </li>
        </ol>
      </div>
      <div className="flex-auto bg-white p-5 overflow-y-scroll rounded-lg text-gray-700">
        {errorMessage !== null && (
          <Alert className="mb-3" level="error">
            {errorMessage}
          </Alert>
        )}
        <form>
          <div className="pb-5">
            <h3 className="text-lg leading-6 font-medium">
              <a name="attributes">Project Attributes</a>
            </h3>
          </div>
          <div className="border-t border-gray-300 w-full pl-5">
            <Field
              title={t('project.name')}
              name="name"
              type="text"
              autoFocus={true}
              required={true}
            />
            <Field
              title={t('project.team')}
              name="owned_by"
              type="select"
              options={metadata.teams !== null ? metadata.teams : []}
              required={true}
            />
            <Field
              title={t('project.projectType')}
              name="project_type"
              type="select"
              options={
                metadata.projectTypes !== null ? metadata.projectTypes : []
              }
              required={true}
            />
            <Field
              title={t('project.dataCenter')}
              name="data_center"
              type="select"
              options={
                metadata.dataCenters !== null ? metadata.dataCenters : []
              }
            />
            <Field
              title={t('project.environments')}
              name="environments"
              type="select"
              multiple={true}
              options={
                metadata.environments !== null ? metadata.environments : []
              }
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
            />
          </div>

          <div className="pt-10 pb-5">
            <h3 className="text-lg leading-6 font-medium text-gray-700">
              <a name="automations">Automations</a>
            </h3>
          </div>
          <div className="border-t border-gray-300 w-full pl-5"></div>

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

          <div className="pt-10 pb-5">
            <h3 className="text-lg leading-6 font-medium text-gray-700">
              <a name="dependencies">Project Dependencies</a>
            </h3>
          </div>
          <div className="border-t border-gray-300 w-full pl-5"></div>

          <div className="flex flex-row border-t border-gray-300 mt-5 pt-5">
            <div className="flex-shrink text-xs pl-2">
              <sup className="mr-2">*</sup> {t('common.required')}
            </div>
            <div className="flex-grow text-right space-x-3">
              <Button
                className="btn-white"
                onClick={() => {
                  console.log('Close')
                }}>
                {t('common.cancel')}
              </Button>
              <Button className="btn-green" disabled={true} type="submit">
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
