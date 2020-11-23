import React, { useEffect, useState } from 'react'

import { Button, Jumbotron } from 'reactstrap'
import { Link } from '@reach/router'
import PropTypes from 'prop-types'

import Alert from './Alert'
import Breadcrumb from './Breadcrumb'
import { Columns, Table } from './Table/'
import CRUDIndex from './AdminCRUD'

export const propTypes = {
    addClickCallback: PropTypes.func,
    addPath: PropTypes.string,
    breadcrumbItems: PropTypes.arrayOf(
        PropTypes.shape({
            icon: PropTypes.string,
            path: PropTypes.path,
            title: PropTypes.string,
        })
    ),
    columns: Columns,
    data: PropTypes.arrayOf(PropTypes.object),
    defaultFilter: PropTypes.string,
    deleteCallback: PropTypes.func,
    errorMessage: PropTypes.string,
    keyField: PropTypes.string,
    successMessage: PropTypes.string,
    title: PropTypes.string,
    updateCallback: PropTypes.func,
    validationCallback: PropTypes.func,
}

export default function (props) {
    const [errorMessage, setErrorMessage] = useState(props.errorMessage)
    const [successMessage, setSuccessMessage] = useState(props.successMessage)

    useEffect(() => {
        setErrorMessage(props.errorMessage)
    }, [props.errorMessage])

    useEffect(() => {
        setSuccessMessage(props.successMessage)
    }, [props.successMessage])

    return (
        <div className="container-fluid">
            <div className="row align-items-center topbar">
                <div className="col-6">
                    <Breadcrumb items={props.breadcrumbItems} title={props.title} />
                </div>
                <div className="col-6 text-right">
                    <div className="form-inline float-right">
                        {props.addPath !== undefined && (
                            <Link
                                key="crudAddButton"
                                to={props.addPath}
                                className="btn btn-primary btn-sm"
                            >
                                <span className="fas fa-plus-circle" /> Add{' '}
                                {props.title}
                            </Link>
                        )}
                        {props.addClickCallback !== undefined && (
                            <Button
                                color="primary"
                                onClick={props.addClickCallback}
                                size="sm"
                            >
                                <span className="fas fa-plus-circle" /> Add{' '}
                                {props.title}
                            </Button>
                        )}
                    </div>
                </div>
            </div>
            {successMessage && <Alert color="success">{successMessage}</Alert>}
            {errorMessage && <Alert color="warning">{errorMessage}</Alert>}
            <Table
                columns={props.columns}
                data={props.data}
                keyField={props.keyField}
                sortColumn={
                    props.sortColumn !== undefined
                        ? props.sortColumn
                        : props.keyField
                }
                sortDirection="asc"
                deleteCallback={props.deleteCallback}
                updateCallback={props.updateCallback}
                validationCallback={props.validationCallback}
            >
                <Jumbotron>
                    <h2>No {props.title} records</h2>
                    <hr className="my-2" />
                    <p>
                        Click the &ldquo;Add {props.title}&rdquo; button above
                        and to the right to add your first record.
                    </p>
                </Jumbotron>
            </Table>
        </div>
    )
}
