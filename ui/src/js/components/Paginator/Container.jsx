import PropTypes from 'prop-types'
import React, { useEffect, useState } from 'react'

import { Context } from './Context'

function Container({
  adjacentPages,
  children,
  itemCount,
  itemsPerPage,
  offset,
  onChange,
  onPageSize
}) {
  const [currentPage, setCurrentPage] = useState(1)
  const [displayState, setDisplayState] = useState({
    offset: offset,
    startPage: 1,
    lastPage: 0,
    nextPage: 2,
    prevPage: 1,
    pages: []
  })
  const pages = [...Array(itemCount).keys()].map((p) => p + 1)
  const [pageCount, setPageCount] = useState(
    Math.ceil(itemCount / itemsPerPage)
  )
  const [pageSize, setPageSize] = useState(itemsPerPage)

  useEffect(() => {
    setPageCount(Math.ceil(itemCount / pageSize))
    onPageSize(pageSize)
  }, [pageSize])

  useEffect(() => {
    const currentOffset = (currentPage - 1) * pageSize
    const startPage = Math.max(currentPage - adjacentPages, 1)
    const lastPage = Math.min(currentPage + adjacentPages, pageCount)
    setDisplayState({
      offset: currentOffset,
      startPage: startPage,
      lastPage: lastPage,
      nextPage: currentPage + 1,
      prevPage: currentPage - 1,
      pages: pages.slice(startPage - 1, startPage + (lastPage - startPage))
    })
    onChange(currentOffset)
  }, [currentPage])

  return (
    <Context.Provider
      value={{
        adjacentPages: adjacentPages,
        currentPage: currentPage,
        itemCount: itemCount,
        offset: displayState.offset,
        lastPage: displayState.lastPage,
        nextPage: displayState.nextPage,
        pages: displayState.pages,
        prevPage: displayState.prevPage,
        pageCount: pageCount,
        pageSize: pageSize,
        setCurrentPage: setCurrentPage,
        setPageSize: setPageSize,
        startPage: displayState.startPage
      }}>
      {children}
    </Context.Provider>
  )
}
Container.defaultProps = {
  adjacentPages: 2,
  itemsPerPage: 25
}
Container.propTypes = {
  adjacentPages: PropTypes.number,
  children: PropTypes.arrayOf(PropTypes.element).isRequired,
  itemCount: PropTypes.number.isRequired,
  itemsPerPage: PropTypes.number,
  offset: PropTypes.number.isRequired,
  onChange: PropTypes.func.isRequired,
  onPageSize: PropTypes.func
}
export { Container }
