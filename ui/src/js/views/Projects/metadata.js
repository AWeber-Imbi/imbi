import { fetchSettings } from '../../settings'

export function fetchMetadata(fetch, onSuccess, onError) {
  const data = {
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
  }
  let erred = false

  function onData(key, options) {
    data[key] = options
    if (Object.values(data).includes(null) === false && erred === false) {
      data.ready = true
      onSuccess(data)
    }
  }

  function onErr(value) {
    erred = true
    onError(value)
  }

  fetchSettings(
    fetch,
    '/settings/configuration_systems',
    true,
    (data) => {
      onData('configurationSystems', data)
    },
    onErr
  )
  fetchSettings(
    fetch,
    '/settings/cookie_cutters',
    true,
    (data) => {
      onData('cookieCutters', data)
    },
    onErr
  )
  fetchSettings(
    fetch,
    '/settings/data_centers',
    true,
    (data) => {
      onData('dataCenters', data)
    },
    onErr
  )
  fetchSettings(
    fetch,
    '/settings/deployment_types',
    true,
    (data) => {
      onData('deploymentTypes', data)
    },
    onErr
  )
  fetchSettings(
    fetch,
    '/settings/environments',
    true,
    (data) => {
      onData('environments', data)
    },
    onErr
  )
  fetchSettings(
    fetch,
    '/settings/orchestration_systems',
    true,
    (data) => {
      onData('orchestrationSystems', data)
    },
    onErr
  )
  fetchSettings(
    fetch,
    '/settings/project_link_types',
    false,
    (data) => {
      onData('projectLinkTypes', data)
    },
    onErr
  )
  fetchSettings(
    fetch,
    '/settings/project_types',
    true,
    (data) => {
      onData('projectTypes', data)
    },
    onErr
  )
  fetchSettings(
    fetch,
    '/settings/teams',
    true,
    (data) => {
      onData('teams', data)
    },
    onErr
  )
}
