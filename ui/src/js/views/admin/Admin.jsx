import React, {useContext} from 'react'
import {
  faBox, faBuilding, faCogs, faCookie, faCubes, faExternalLinkAlt,
  faRuler, faTree, faUserFriends, faUsers
} from "@fortawesome/free-solid-svg-icons";

import {Router, Sidebar} from '../../components'
import {UserContext} from '../../contexts'
import {default as ConfigurationSystems} from './ConfigurationSystems'


function Admin() {
  const currentUser = useContext(UserContext)
  if (currentUser.authenticated !== true) return null
  return (
    <div className="flex-auto flex flex-row">
      <Sidebar title="Administration">
        <Sidebar.Section name="Settings" open={true}>
          <Sidebar.MenuItem value="Configuration Systems" to="configuration-systems" icon={faBox} />
          <Sidebar.MenuItem value="Cookie Cutters" to="/ui/admin/cookie-cutters" icon={faCookie} />
          <Sidebar.MenuItem value="Data Centers" to="/ui/admin/data-centers" icon={faBuilding} />
          <Sidebar.MenuItem value="Environments" to="/ui/admin/environments" icon={faTree} />
          <Sidebar.MenuItem value="Orchestration Systems" to="/ui/admin/orchestration-systems" icon={faCogs} />
          <Sidebar.MenuItem value="Project Fact Types" to="/ui/admin/project-fact-types" icon={faRuler} />
          <Sidebar.MenuItem value="Project Link Types" to="/ui/admin/project-link-types" icon={faExternalLinkAlt} />
          <Sidebar.MenuItem value="Project Types" to="/ui/admin/project-types" icon={faCubes} />
        </Sidebar.Section>
        <Sidebar.Section name="User Management">
          <Sidebar.MenuItem value="Users" to="/ui/admin/users" icon={faUserFriends} />
          <Sidebar.MenuItem value="Groups" to="/ui/admin/groups" icon={faUsers} />
        </Sidebar.Section>
      </Sidebar>
      <div className="flex flex-col w-auto p-4">
        <Router>
          <ConfigurationSystems path="configuration-systems" />
        </Router>
      </div>
    </div>
  )
}

Admin.propTypes = {}

export default Admin
