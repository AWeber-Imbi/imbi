export function getErrorMessage(response, data) {
  return (data && data.title) || response.status + ': ' + response.statusText
}

export function isFunction(func) {
  return func && {}.toString.call(func) === '[object Function]'
}

export const requestOptions = {
  method: 'GET',
  headers: {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    Pragma: 'no-cache',
    'User-Agent': 'imbi-ui'
  },
  init: { credentials: 'include' }
}

export function httpGet(fetchMethod, path, onSuccess, onError) {
  httpRequest(fetchMethod, path, requestOptions).then(({ data, success }) => {
    success ? onSuccess(data) : onError(data)
  })
}

export function httpDelete(fetchMethod, path) {
  return httpRequest(fetchMethod, path, {
    ...requestOptions,
    method: 'DELETE'
  })
}

export function httpPatch(fetchMethod, path, body) {
  return httpRequest(fetchMethod, path, {
    ...requestOptions,
    method: 'PATCH',
    body: JSON.stringify(body),
    headers: {
      ...requestOptions.headers,
      'Content-Type': 'application/json-patch+json'
    }
  })
}

export function httpPost(fetchMethod, path, body, options = {}) {
  return httpRequest(fetchMethod, path, {
    ...requestOptions,
    method: 'POST',
    body: JSON.stringify(body),
    ...options
  })
}

export async function httpRequest(fetchMethod, path, options = requestOptions) {
  const response = await fetchMethod(path, options)
  const text = await response.text()
  const data = text && JSON.parse(text)
  if (response.status >= 200 && response.status < 300)
    return { success: true, data: data }
  return { success: false, data: getErrorMessage(response, data) }
}

export function setDocumentTitle(value) {
  document.title = 'Imbi - ' + value
}
