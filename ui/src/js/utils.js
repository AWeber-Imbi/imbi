export function getErrorMessage(response, data) {
  return (
    (data && data.message) || response.status + ": " + response.statusText
  )
}

export function isFunction(func) {
  return func && {}.toString.call(func) === "[object Function]"
}

export const requestOptions = {
  method: "GET",
  headers: {
    Accept: "application/json",
    "Content-Type": "application/json",
    Pragma: "no-cache",
    "User-Agent": "imbi-ui",
  },
  init: {credentials: "include"},
}

export async function httpGet(
  fetchMethod,
  path,
  onSuccess = undefined,
  onError = undefined
) {
  const result = await httpRequest(fetchMethod, path, requestOptions)
  if (result.success === true) {
    if (isFunction(onSuccess)) onSuccess(result.data)
  } else {
    if (isFunction(onError)) onError(result.data)
  }
}

export function httpDelete(fetchMethod, path) {
  return httpRequest(fetchMethod, path, {
    ...requestOptions,
    method: "DELETE",
  })
}

export function httpPatch(fetchMethod, path, body) {
  return httpRequest(fetchMethod, path, {
    ...requestOptions,
    method: "PATCH",
    body: JSON.stringify(body),
    headers: {
      ...requestOptions.headers,
      "Content-Type": "application/json-patch+json",
    },
  })
}

export function httpPost(fetchMethod, path, body, options = {}) {
  return httpRequest(fetchMethod, path, {
    ...requestOptions,
    method: "POST",
    body: JSON.stringify(body),
    ...options,
  })
}

export async function httpRequest(fetchMethod, path, options = requestOptions) {
  const response = await fetchMethod(path, options)
  const text = await response.text()
  const data = text && JSON.parse(text)
  if (response.status >= 200 && response.status < 300)
    return {success: true, data: data}
  return {success: false, data: getErrorMessage(response, data)}
}
