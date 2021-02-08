import PropTypes from 'prop-types'
import React, { useEffect, useState } from 'react'

import { Buttons } from './Buttons'
import { Context } from './Context'
import { PageSizeSelector } from './PageSizeSelector'
import { StateDisplay } from './StateDisplay'

function Paginator({
  adjacentPages,
  itemCount,
  itemsPerPage,
  offset,
  onChange,
  onPageSize,
  positionNounSingular,
  positionNounPlural,
  showPageSizeSelector,
  showStateDisplay
}) {
  const [currentPage, setCurrentPage] = useState(1)
  const pages = [...Array(itemCount).keys()].map((p) => p + 1)
  const [pageCount, setPageCount] = useState(
    Math.ceil(itemCount / itemsPerPage)
  )
  const [pageSize, setPageSize] = useState(itemsPerPage)
  const [state, setState] = useState({
    offset: offset,
    startPage: 1,
    lastPage: adjacentPages + 1,
    nextPage: 2,
    prevPage: 0,
    pages: []
  })

  useEffect(() => {
    setPageCount(Math.ceil(itemCount / pageSize))
    onPageSize(pageSize)
  }, [pageSize])

  useEffect(() => {
    const currentOffset = (currentPage - 1) * itemsPerPage
    const startPage = Math.max(currentPage - adjacentPages, 1)
    const lastPage = Math.min(currentPage + adjacentPages, pageCount)
    setState({
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
        offset: state.offset,
        lastPage: state.lastPage,
        nextPage: state.nextPage,
        pages: state.pages,
        prevPage: state.prevPage,
        pageCount: pageCount,
        pageSize: pageSize,
        setCurrentPage: setCurrentPage,
        setPageSize: setPageSize,
        startPage: state.startPage
      }}>
      <div className="align-middle flex flex-column mt-3">
        <StateDisplay
          display={showStateDisplay}
          nounPlural={positionNounPlural}
          nounSingular={positionNounSingular}
        />
        <PageSizeSelector display={showPageSizeSelector} />
        <Buttons />
      </div>
    </Context.Provider>
  )
}
Paginator.defaultProps = {
  adjacentPages: 2,
  itemsPerPage: 25,
  showPageSizeSelector: false,
  showStateDisplay: false
}
Paginator.propTypes = {
  adjacentPages: PropTypes.number,
  itemCount: PropTypes.number.isRequired,
  itemsPerPage: PropTypes.number,
  offset: PropTypes.number.isRequired,
  onChange: PropTypes.func.isRequired,
  onPageSize: PropTypes.func,
  positionNounSingular: PropTypes.string,
  positionNounPlural: PropTypes.string,
  showPageSizeSelector: PropTypes.bool,
  showStateDisplay: PropTypes.bool
}
export { Paginator }
