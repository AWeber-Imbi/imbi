import { fetchMetadata as _fetchMetadata } from '../../metadata'

export function fetchMetadata(fetch, onSuccess, onError) {
  const data = {
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

  _fetchMetadata(
    fetch,
    '/configuration-systems',
    true,
    'name',
    'name',
    (data) => {
      onData('configurationSystems', data)
    },
    onErr
  )

  _fetchMetadata(
    fetch,
    '/cookie-cutters',
    false,
    null,
    null,
    (data) => {
      onData('cookieCutters', data)
    },
    onErr
  )

  _fetchMetadata(
    fetch,
    '/data-centers',
    true,
    'name',
    'name',
    (data) => {
      onData('dataCenters', data)
    },
    onErr
  )

  _fetchMetadata(
    fetch,
    '/deployment-types',
    true,
    'name',
    'name',
    (data) => {
      onData('deploymentTypes', data)
    },
    onErr
  )

  _fetchMetadata(
    fetch,
    '/environments',
    true,
    'name',
    'name',
    (data) => {
      onData('environments', data)
    },
    onErr
  )

  _fetchMetadata(
    fetch,
    '/namespaces',
    true,
    'name',
    'id',
    (data) => {
      onData('namespaces', data)
    },
    onErr
  )

  _fetchMetadata(
    fetch,
    '/orchestration-systems',
    true,
    'name',
    'name',
    (data) => {
      onData('orchestrationSystems', data)
    },
    onErr
  )

  _fetchMetadata(
    fetch,
    '/project-link-types',
    false,
    '',
    '',
    (data) => {
      onData('projectLinkTypes', data)
    },
    onErr
  )

  _fetchMetadata(
    fetch,
    '/project-types',
    true,
    'name',
    'id',
    (data) => {
      onData('projectTypes', data)
    },
    onErr
  )
}
