import PropTypes from 'prop-types'
import React from 'react'
import { Route } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { Error } from '../'
import { setDocumentTitle } from '../../utils'
import { Sidebar } from '../../components'
import { User } from '../../schema'

import { ConfigurationSystems } from './ConfigurationSystems'
import { CookieCutters } from './CookieCutters'
import { DataCenters } from './DataCenters'
import { DeploymentTypes } from './DeploymentTypes'
import { Environments } from './Environments'
import { OrchestrationSystems } from './OrchestrationSystems'
import { ProjectFactTypes } from './ProjectFactTypes'
import { ProjectLinkTypes } from './ProjectLinkTypes'
import { ProjectTypes } from './ProjectTypes'

function Admin({ user }) {
  const { t } = useTranslation()
  setDocumentTitle(t('admin.title'))
  if (user.permissions.includes('admin') !== true)
    return <Error>{t('common.accessDenied')}</Error>
  return (
    <div className="flex-auto flex flex-row">
      <Sidebar title={t('admin.title')}>
        <Sidebar.Section name={t('admin.sidebar.settings')} open={true}>
          <Sidebar.MenuItem
            value={t('admin.configurationSystems.collectionName')}
            to="/ui/admin/configuration-systems"
            icon="fas box"
          />
          <Sidebar.MenuItem
            value={t('admin.cookieCutters.collectionName')}
            to="/ui/admin/cookie-cutters"
            icon="fas cookie"
          />
          <Sidebar.MenuItem
            value={t('admin.dataCenters.collectionName')}
            to="/ui/admin/data-centers"
            icon="fas building"
          />
          <Sidebar.MenuItem
            value={t('admin.deploymentTypes.collectionName')}
            to="/ui/admin/deployment-types"
            icon="fas upload"
          />
          <Sidebar.MenuItem
            value={t('admin.environments.collectionName')}
            to="/ui/admin/environments"
            icon="fas tree"
          />
          <Sidebar.MenuItem
            value={t('admin.orchestrationSystems.collectionName')}
            to="/ui/admin/orchestration-systems"
            icon="fas cogs"
          />
          <Sidebar.MenuItem
            value={t('admin.projectFactTypes.collectionName')}
            to="/ui/admin/project-fact-types"
            icon="fas ruler"
          />
          <Sidebar.MenuItem
            value={t('admin.projectLinkTypes.collectionName')}
            to="/ui/admin/project-link-types"
            icon="fas external-link-alt"
          />
          <Sidebar.MenuItem
            value={t('admin.projectTypes.collectionName')}
            to="/ui/admin/project-types"
            icon="fas cubes"
          />
        </Sidebar.Section>
        <Sidebar.Section name={t('admin.sidebar.userManagement')}>
          <Sidebar.MenuItem
            value="Users"
            to="/ui/admin/users"
            icon="fas user-friends"
          />
          <Sidebar.MenuItem
            value="Groups"
            to="/ui/admin/groups"
            icon="fas users"
          />
        </Sidebar.Section>
      </Sidebar>
      <div className="flex-auto w-full p-4">
        <Route
          path="/ui/admin/configuration-systems"
          component={ConfigurationSystems}
        />
        <Route path="/ui/admin/cookie-cutters" component={CookieCutters} />
        <Route path="/ui/admin/data-centers" component={DataCenters} />
        <Route path="/ui/admin/deployment-types" component={DeploymentTypes} />
        <Route path="/ui/admin/environments" component={Environments} />
        <Route
          path="/ui/admin/orchestration-systems"
          component={OrchestrationSystems}
        />
        <Route
          path="/ui/admin/project-fact-types"
          component={ProjectFactTypes}
        />
        <Route
          path="/ui/admin/project-link-types"
          component={ProjectLinkTypes}
        />
        <Route path="/ui/admin/project-types" component={ProjectTypes} />
      </div>
    </div>
  )
}

Admin.propTypes = {
  match: PropTypes.object,
  user: PropTypes.exact(User)
}

export { Admin }
