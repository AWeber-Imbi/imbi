import PropTypes from 'prop-types'
import React, { Fragment } from 'react'

import { Button, Card, Icon } from '../../components'
import { useTranslation } from 'react-i18next'

import { Edit } from './Edit'

function Definition({ term, icon, children, className }) {
  return (
    <Fragment>
      <dt className="font-medium text-gray-500 w-48">{term}</dt>
      <dd
        className={`mt-1 items-start sm:mt-0 truncate ${
          className !== undefined ? className : ''
        }`}>
        {icon && <Icon icon={icon} className="mr-2 " />}
        {children}
      </dd>
    </Fragment>
  )
}
Definition.propTypes = {
  term: PropTypes.string.isRequired,
  icon: PropTypes.string,
  children: PropTypes.oneOfType([
    PropTypes.element,
    PropTypes.string,
    PropTypes.arrayOf(PropTypes.element)
  ]),
  className: PropTypes.string
}

function Display({ project, onEditClick, shouldGrow }) {
  const { t } = useTranslation()
  return (
    <Card className={`flex flex-col ${shouldGrow ? 'h-full' : ''}`}>
      <Fragment>
        <h2 className="font-medium mb-2">{t('terms.projectInfo')}</h2>
        <dl className="lg:ml-4 my-3 space-y-3 overflow-hidden text-gray-900">
          <Definition term={t('terms.namespace')} icon={project.namespace_icon}>
            {project.namespace}
          </Definition>
          <Definition term={t('terms.projectType')} icon={project.project_icon}>
            {project.project_type}
          </Definition>
          <Definition term={t('terms.slug')} className="font-mono">
            {project.slug}
          </Definition>
          {project.environments && project.environments.length > 0 && (
            <Definition term={t('terms.environments')}>
              {project.environments.join(', ')}
            </Definition>
          )}
          {project.environments &&
            project.environments.map((environment) => {
              if (project.urls[environment] === undefined) return null
              return (
                <Definition
                  key={`display-${environment}-url`}
                  term={`${environment} URL`}>
                  <a
                    className="text-blue-800 hover:text-blue-700"
                    title={project.urls[environment]}
                    href={project.urls[environment]}
                    target="_new">
                    <Icon icon="fas external-link-alt" className="mr-2" />
                    {project.urls[environment]}{' '}
                  </a>
                </Definition>
              )
            })}
          {project.links.map((link, index) => {
            return (
              <Definition key={`display-link-${index}`} term={link.title}>
                <a
                  className="text-blue-800 hover:text-blue-700"
                  href={link.url}
                  title={link.url}
                  target="_new">
                  <Icon icon="fas external-link-alt" className="mr-2" />
                  {link.url}{' '}
                </a>
              </Definition>
            )
          })}
        </dl>
        {project.archived === false && (
          <div className="flex-grow flex flex-row items-end">
            <div className="flex-grow text-right mt-2">
              <Button className="btn-white text-xs" onClick={onEditClick}>
                <Icon icon="fas edit" className="mr-2" />
                {t('project.editProject')}
              </Button>
            </div>
          </div>
        )}
      </Fragment>
    </Card>
  )
}
Display.propTypes = {
  project: PropTypes.object.isRequired,
  onEditClick: PropTypes.func.isRequired,
  shouldGrow: PropTypes.bool.isRequired
}

function Details({ project, editing, onEditing, refresh, shouldGrow }) {
  if (editing)
    return (
      <Edit
        project={project}
        onEditFinished={(refreshProject) => {
          onEditing(false)
          if (refreshProject === true) refresh()
        }}
      />
    )
  return (
    <Display
      project={project}
      onEditClick={() => onEditing(true)}
      shouldGrow={shouldGrow}
    />
  )
}
Details.propTypes = {
  project: PropTypes.object.isRequired,
  editing: PropTypes.bool.isRequired,
  onEditing: PropTypes.func.isRequired,
  refresh: PropTypes.func.isRequired,
  shouldGrow: PropTypes.bool.isRequired
}
export { Details }
