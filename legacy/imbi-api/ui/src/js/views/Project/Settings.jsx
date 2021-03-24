import { compare } from 'fast-json-patch'
import PropTypes from 'prop-types'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { useHistory } from 'react-router-dom'

import { Backdrop, Button, Card, ConfirmationDialog } from '../../components'
import { Context } from '../../state'
import { httpDelete, httpPatch } from '../../utils'

async function archiveProject(globalState, project) {
  const originalValues = {
    archived: project.archived
  }
  const values = {
    archived: true
  }
  const patchValue = compare(originalValues, values)
  if (patchValue.length > 0) {
    const projectURL = new URL(`/projects/${project.id}`, globalState.baseURL)
    const result = await httpPatch(globalState.fetch, projectURL, patchValue)
    if (result.success === false) {
      return [false, result.data]
    }
  }
  return [true, null]
}

function Settings({ project, refresh, urlPath }) {
  const [globalState, dispatch] = useContext(Context)
  const history = useHistory()
  const [state, setState] = useState({
    showArchiveConfirmation: false,
    showBackdrop: false,
    showDeleteConfirmation: false
  })
  useEffect(() => {
    dispatch({
      type: 'SET_CURRENT_PAGE',
      payload: {
        title: 'common.settings',
        url: new URL(`${urlPath}/settings`, globalState.baseURL)
      }
    })
  }, [])

  async function onArchive() {
    setState({ ...state, showArchiveConfirmation: false, showBackdrop: true })
    await archiveProject(globalState, project)
    refresh()
    history.push(urlPath)
  }

  async function onDelete() {
    setState({ ...state, showDeleteConfirmation: false, showBackdrop: true })
    const projectURL = new URL(`/projects/${project.id}`, globalState.baseURL)
    const result = await httpDelete(globalState.fetch, projectURL)
    if (result.success === false) {
      refresh()
      return history.push(urlPath)
    }
    const url = new URL('/ui/projects/', globalState.baseURL)
    url.searchParams.append(
      'message',
      `${project.name} was successfully deleted.`
    )
    history.replace(`${url.pathname}${url.search}`)
  }

  return (
    <Fragment>
      {state.showBackdrop && <Backdrop />}
      {state.showArchiveConfirmation && (
        <ConfirmationDialog
          mode="warning"
          onCancel={() =>
            setState({ ...state, showArchiveConfirmation: false })
          }
          onConfirm={onArchive}
          title={`Archive ${project.name}?`}
          confirmationButtonText={`Archive ${project.name}`}>
          <div className="space-y-4">
            <p>Archiving the project will make it entirely read only.</p>
            <p>
              It will be hidden from the dashboard, won&rsquo;t show up in
              searches, and will be disabled as a dependency for any other
              projects that are dependent upon it.
            </p>
            <p className="font-semibold">
              Are you sure you want to archive this project?
            </p>
          </div>
        </ConfirmationDialog>
      )}
      {state.showDeleteConfirmation && (
        <ConfirmationDialog
          mode="error"
          onCancel={() => setState({ ...state, showDeleteConfirmation: false })}
          onConfirm={onDelete}
          title={`Delete ${project.name}?`}
          confirmationButtonText={`Delete ${project.name}`}>
          <div className="space-y-4">
            <p>
              This action will immediately and permanently delete the project,
              all associated data, including facts, operation logs, and notes.
            </p>
            <p className="font-semibold">
              Are you ABSOLUTELY SURE you wish to delete this project?
            </p>
          </div>
        </ConfirmationDialog>
      )}
      <Card className="space-y-10">
        <div className="space-y-3">
          <h1 className="border-b border-gray-300 font-bold pb-2 text-xl text-yellow-700">
            Archive Project
          </h1>
          <div className="ml-2 space-y-3">
            <p>Archiving the project will make it entirely read only.</p>
            <p className="font-semibold">
              It will be hidden from the dashboard, won&rsquo;t show up in
              searches, and will be disabled as a dependency for any other
              projects that are dependent upon it.
            </p>
          </div>
          <Button
            className="btn-yellow text-sm"
            onClick={() => {
              setState({ ...state, showArchiveConfirmation: true })
            }}>
            Archive Project
          </Button>
        </div>
        <div className="space-y-3">
          <h1 className="border-b border-gray-300 font-bold pb-2 text-xl text-red-700">
            Delete Project
          </h1>
          <div className="ml-2 space-y-3">
            <p>
              This action will{' '}
              <span className="font-semibold">
                permanently delete{' '}
                <span className="border border-gray-400 font-normal font-mono mx-1 px-1.5 py-1">
                  {project.name}
                </span>{' '}
                immediately
              </span>
              , removing the project and all associated data, including facts,
              operation logs, and notes.
            </p>
            <p className="font-semibold">
              Are you ABSOLUTELY SURE you wish to delete this project?
            </p>
          </div>
          <Button
            className="btn-red text-sm"
            onClick={() => {
              setState({ ...state, showDeleteConfirmation: true })
            }}>
            Delete Project
          </Button>
        </div>
      </Card>
    </Fragment>
  )
}
Settings.propTypes = {
  project: PropTypes.object.isRequired,
  refresh: PropTypes.func.isRequired,
  urlPath: PropTypes.string.isRequired
}
export { Settings }
