import { httpGet } from './utils'

export function fetchMetadata(
  fetch,
  path,
  asOptions,
  optionLabel,
  optionValue,
  onSuccess,
  onError
) {
  const url = new URL(fetch.baseURL)
  url.pathname = path
  httpGet(
    fetch.function,
    url,
    (data) => {
      if (asOptions) {
        const options = []
        data.map((value) => {
          options.push({
            label: value[optionLabel],
            value: value[optionValue]
          })
        })
        onSuccess(options)
      } else {
        onSuccess(data)
      }
    },
    onError
  )
}
