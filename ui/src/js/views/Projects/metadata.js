import { fetchMetadata as _fetchMetadata } from '../../metadata'

export function fetchMetadata(fetch, onSuccess, onError) {
  const data = {
    cookieCutters: null,
    environments: null,
    namespaces: null,
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
