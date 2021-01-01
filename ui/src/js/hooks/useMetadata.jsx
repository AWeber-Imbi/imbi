import {useContext, useEffect, useState} from "react"

import {FetchContext} from "../contexts"
import {httpGet} from "../utils"

let cachedData = null
const path = "/ui/settings"

export default function (useCache = false) {
  const fetchMethod = useContext(FetchContext)

  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    cachedData = data
  }, [data])

  useEffect(() => {
    if (useCache === true && cachedData !== null) {
      setData(cachedData)
    } else {
      httpGet(fetchMethod, path, setData, setError)
    }
  }, [useCache])

  if (data === null && cachedData == null)
    httpGet(fetchMethod, path, setData, setError)

  return [data, error]
}
