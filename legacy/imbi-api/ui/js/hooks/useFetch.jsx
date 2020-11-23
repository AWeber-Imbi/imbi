import React, { useContext, useEffect, useState } from 'react'

import { FetchContext } from '../contexts'
import { httpGet } from '../utils'

let cachedData = {}

export default function (
    path,
    defaultValue = undefined,
    useCache = false,
    dataIndex = 0
) {
    const fetchMethod = useContext(FetchContext)
    const [data, setData] = useState(defaultValue)
    const [errorMessage, setErrorMessage] = useState(undefined)

    // Clear the cache when we know we want to refresh it
    if (dataIndex > 0 && useCache === true) cachedData[path] = undefined

    function onFetch(result) {
        if (useCache === true) cachedData[path] = result
        setData(result)
    }

    useEffect(() => {
        if (useCache === true && cachedData[path] !== defaultValue) {
            setData(cachedData[path])
        } else {
            httpGet(fetchMethod, path, onFetch, setErrorMessage)
        }
    }, [path, dataIndex])
    return [data, errorMessage]
}
