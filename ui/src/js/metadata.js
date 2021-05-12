import PropTypes from 'prop-types'
import { useContext, useEffect, useState } from 'react'

import { httpGet } from './utils'
import { Context } from './state'

const RefreshAfter = 300000

function asOptions(data, value = 'id', label = 'name') {
  return data.map((item) => {
    return { label: item[label], value: item[value] }
  })
}
asOptions.propTypes = {
  data: PropTypes.arrayOf(PropTypes.object),
  id: PropTypes.string,
  label: PropTypes.string
}

function useMetadata(externalRefresh = false) {
  const [state] = useContext(Context)
  const [cookieCutters, setCookieCutters] = useState(null)
  const [environments, setEnvironments] = useState(null)
  const [groups, setGroups] = useState(null)
  const [namespaces, setNamespaces] = useState(null)
  const [projectFactTypes, setProjectFactTypes] = useState(null)
  const [projectLinkTypes, setProjectLinkTypes] = useState(null)
  const [projectTypes, setProjectTypes] = useState(null)
  const [errors, setErrors] = useState({
    cookieCutters: null,
    environments: null,
    groups: null,
    namespaces: null,
    projectFactTypes: null,
    projectLinkTypes: null,
    projectTypes: null
  })
  const [lastUpdated, setLastUpdated] = useState(null)
  const [timerHandle, setTimerHandle] = useState(null)
  const [refresh, setRefresh] = useState(true)
  const [values, setValues] = useState(undefined)
  const [gitlabDetails, setGitlabDetails] = useState({
    authorizationEndpoint: null,
    clientId: null,
    redirectURI: null
  })

  function processGitlabResponse(data) {
    setGitlabDetails({
      ...gitlabDetails,
      authorizationEndpoint: data.authorization_endpoint,
      clientId: data.client_id,
      redirectURI: data.callback_url
    })
  }

  function get(path, onSuccess, key) {
    httpGet(state.fetch, new URL(path, state.baseURL), onSuccess, (error) => {
      setErrors({ ...errors, [key]: error })
    })
  }
  get.propTypes = {
    path: PropTypes.string.isRequired,
    onSuccess: PropTypes.func.isRequired,
    key: PropTypes.string.isRequired
  }

  useEffect(() => {
    if (lastUpdated === null || externalRefresh === true || refresh === true) {
      get('/cookie-cutters', setCookieCutters, 'cookieCutters')
      get('/environments', setEnvironments, 'environments')
      get('/groups', setGroups, 'groups')
      get('/namespaces', setNamespaces, 'namespaces')
      get('/project-fact-types', setProjectFactTypes, 'projectFactTypes')
      get('/project-link-types', setProjectLinkTypes, 'projectLinkTypes')
      get('/project-types', setProjectTypes, 'projectTypes')
      get('/integrations/gitlab', processGitlabResponse, '')
      setLastUpdated(Date.now())
      setRefresh(false)
    }
  }, [externalRefresh, refresh])

  useEffect(() => {
    if (timerHandle !== null) {
      clearTimeout(timerHandle)
    }
    const handle = setTimeout(() => {
      setRefresh(true)
      setTimerHandle(null)
    }, RefreshAfter)
    setTimerHandle(handle)
    return function cleanup() {
      clearTimeout(handle)
    }
  }, [lastUpdated])

  useEffect(() => {
    if (
      cookieCutters !== null &&
      environments !== null &&
      groups !== null &&
      namespaces !== null &&
      projectFactTypes !== null &&
      projectLinkTypes !== null &&
      projectTypes !== null
    ) {
      setValues({
        cookieCutters: cookieCutters,
        environments: environments,
        gitlabDetails: gitlabDetails,
        groups: groups,
        namespaces: namespaces,
        projectFactTypes: projectFactTypes,
        projectLinkTypes: projectLinkTypes,
        projectTypes: projectTypes
      })
    }
  }, [
    cookieCutters,
    environments,
    gitlabDetails,
    groups,
    namespaces,
    projectFactTypes,
    projectTypes,
    projectLinkTypes
  ])
  return values
}
useMetadata.propTypes = {
  refresh: PropTypes.boolean
}
export { asOptions, useMetadata }
