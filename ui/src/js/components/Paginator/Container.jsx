import PropTypes from 'prop-types'
import React from 'react'

import { Context } from './Context'

function Container({
  adjacentPages,
  children,
  currentPage,
  itemCount,
  itemsPerPage,
  setCurrentPage,
  setPageSize
}) {
  const availablePages = [...Array(itemCount).keys()].map((p) => p + 1)
  const pageCount = Math.ceil(itemCount / itemsPerPage)
  const startPage = Math.max(currentPage - adjacentPages, 1)
  const lastPage = Math.min(currentPage + adjacentPages, pageCount)
  const nextPage = currentPage + 1
  const prevPage = currentPage - 1
  const pages = availablePages.slice(
    startPage - 1,
    startPage + (lastPage - startPage)
  )
  return (
    <Context.Provider
      value={{
        adjacentPages: adjacentPages,
        currentPage: currentPage,
        itemCount: itemCount,
        lastPage: lastPage,
        nextPage: nextPage,
        pages: pages,
        prevPage: prevPage,
        pageCount: pageCount,
        pageSize: itemsPerPage,
        setCurrentPage: setCurrentPage,
        setPageSize: setPageSize,
        startPage: startPage
      }}>
      {children}
    </Context.Provider>
  )
}
Container.defaultProps = {
  adjacentPages: 2,
  itemsPerPage: 25,
  offset: 0
}
Container.propTypes = {
  adjacentPages: PropTypes.number,
  children: PropTypes.arrayOf(PropTypes.element).isRequired,
  currentPage: PropTypes.number.isRequired,
  itemCount: PropTypes.number.isRequired,
  itemsPerPage: PropTypes.number,
  setCurrentPage: PropTypes.func.isRequired,
  setPageSize: PropTypes.func
}
export { Container }
