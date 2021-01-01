import React, {useContext} from 'react'
import {useTranslation} from 'react-i18next'

import {Router, Sidebar} from '../../components'
import {UserContext} from '../../contexts'
import {default as ConfigurationSystems} from './ConfigurationSystems'

function Admin() {
  const {t} = useTranslation()
  const currentUser = useContext(UserContext)
  if (currentUser.authenticated !== true) return null
  return (
    <div className="flex-auto flex flex-row">
      <Sidebar title={t("admin.title")}>
        <Sidebar.Section name={t("admin.sidebar.settings")} open={true}>
          <Sidebar.MenuItem value={t("admin.configurationSystems.title")} to="configuration-systems" icon="fas box" />
          <Sidebar.MenuItem value="Cookie Cutters" to="/ui/admin/cookie-cutters" icon="fas cookie" />
          <Sidebar.MenuItem value="Data Centers" to="/ui/admin/data-centers" icon="fas building" />
          <Sidebar.MenuItem value="Environments" to="/ui/admin/environments" icon="fas tree" />
          <Sidebar.MenuItem value="Orchestration Systems" to="/ui/admin/orchestration-systems" icon="fas cogs" />
          <Sidebar.MenuItem value="Project Fact Types" to="/ui/admin/project-fact-types" icon="fas ruler" />
          <Sidebar.MenuItem value="Project Link Types" to="/ui/admin/project-link-types" icon="fas external-link-alt" />
          <Sidebar.MenuItem value="Project Types" to="/ui/admin/project-types" icon="fas cubes" />
        </Sidebar.Section>
        <Sidebar.Section name={t("admin.sidebar.userManagement")}>
          <Sidebar.MenuItem value="Users" to="/ui/admin/users" icon="fas user-friends" />
          <Sidebar.MenuItem value="Groups" to="/ui/admin/groups" icon="fas users" />
        </Sidebar.Section>
      </Sidebar>
      <div className="flex-auto w-full p-4">
        <Router>
          <ConfigurationSystems path="configuration-systems" />
        </Router>
      </div>
    </div>
  )
}

Admin.propTypes = {}

export default Admin
