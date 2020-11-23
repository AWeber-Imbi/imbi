import React from 'react'

import { Router } from '@reach/router'

import ConfigurationSystems from './ConfigurationSystems'
import CookieCutters from './CookieCutters'
import DataCenters from './DataCenters'
import DeploymentTypes from './DeploymentTypes'
import Environments from './Environments'
import Groups from './Groups'
import OrchestrationSystems from './OrchestrationSystems'
import ProjectLinkTypes from './ProjectLinkTypes'
import ProjectTypes from './ProjectTypes'
import Teams from './Teams'

export default () => (
    <Router>
        <ConfigurationSystems path="configuration_systems" />
        <CookieCutters path="cookie_cutters" />
        <DataCenters path="data_centers" />
        <DeploymentTypes path="deployment_types" />
        <Environments path="environments" />
        <Groups path="groups" />
        <OrchestrationSystems path="orchestration_systems" />
        <ProjectLinkTypes path="project_link_types" />
        <ProjectTypes path="project_types" />
        <Teams path="teams" />
    </Router>
)
