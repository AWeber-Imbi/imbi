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
  httpGet(
    fetch,
    path,
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
