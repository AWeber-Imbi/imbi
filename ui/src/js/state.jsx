import PropTypes from 'prop-types'
import React, { createContext, useReducer } from 'react'

import { processBreadcrumbs } from './components/Breadcrumbs'

const Reducer = (state, action) => {
  switch (action.type) {
    case 'SET_CURRENT_PAGE':
      return {
        ...state,
        breadcrumbs: processBreadcrumbs(
          state.breadcrumbs.crumbs,
          action.payload
        )
      }
    case 'HIDE_BREADCRUMBS':
      return {
        ...state,
        breadcrumbs: {
          crumbs: state.breadcrumbs.crumbs,
          display: false
        }
      }
    case 'SHOW_BREADCRUMBS':
      return {
        ...state,
        breadcrumbs: {
          crumbs: state.breadcrumbs.crumbs,
          display: true
        }
      }
    case 'SET_BREADCRUMBS':
      return {
        ...state,
        breadcrumbs: action.payload
      }
    case 'SET_ERROR':
      return {
        ...state,
        errorMessage: action.payload
      }
    case 'SET_METADATA':
      return {
        ...state,
        metadata: action.payload[1],
        refreshMetadata: action.payload[0]
      }
    default:
      return state
  }
}

const initialState = {
  baseURL: null,
  fetch: undefined,
  breadcrumbs: {
    crumbs: [],
    display: false
  },
  errorMessage: null,
  handleLogout: () => {},
  metadata: undefined,
  refreshMetadata: () => {}
}

const State = ({
  baseURL,
  fetchMethod,
  handleLogout,
  setErrorMessage,
  children
}) => {
  const [state, dispatch] = useReducer(Reducer, {
    ...initialState,
    baseURL: baseURL,
    fetch: fetchMethod,
    handleLogout: handleLogout,
    setErrorMessage: setErrorMessage
  })
  return (
    <Context.Provider value={[state, dispatch]}>{children}</Context.Provider>
  )
}
State.propTypes = {
  baseURL: PropTypes.instanceOf(URL).isRequired,
  children: PropTypes.oneOfType([
    PropTypes.element,
    PropTypes.arrayOf(PropTypes.element)
  ]),
  fetchMethod: PropTypes.func.isRequired,
  handleLogout: PropTypes.func.isRequired,
  setErrorMessage: PropTypes.func.isRequired
}
const Context = createContext(initialState)
Context.displayName = 'StateContext'
export { Context }
export default State
