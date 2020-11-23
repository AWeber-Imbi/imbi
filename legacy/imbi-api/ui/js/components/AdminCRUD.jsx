import React, { useContext, useEffect, useState } from 'react'

import { compare } from 'fast-json-patch'
import PropTypes from 'prop-types'

import { Columns } from './Table'
import CRUDIndex from './CRUDIndex'
import ModalForm from './ModalForm'

import { FetchContext } from '../contexts'
import { httpDelete, httpPatch, httpPost } from '../utils'
import { useFetch } from '../hooks'

export const propTypes = {
    addClickCallback: PropTypes.func,
    addPath: PropTypes.string,
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
    const fetchMethod = useContext(FetchContext)

    const [columns, setColumns] = useState([])
    const [dataIndex, setDataIndex] = useState(0)
    const [errorMessage, setErrorMessage] = useState(undefined)
    const [showForm, setShowForm] = useState(false)
    const [successMessage, setSuccessMessage] = useState(undefined)

    const [data, dataErrorMessage] = useFetch(
        props.itemsPath,
        undefined,
        false,
        dataIndex
    )

    if (dataErrorMessage !== undefined) setErrorMessage(dataErrorMessage)

    useEffect(() => {
        setColumns(
            props.columns.map((column) => {
                if (column.editable === undefined) column.editable = true
                if (column.headerStyle === undefined)
                    column.headerStyle = { width: 'auto' }
                if (column.type === undefined) column.type = 'text'
                if (column.type == 'select' && column.required !== true)
                    column.options = [
                        {
                            label:
                                column.placeholder !== undefined
                                    ? column.placeholder
                                    : '',
                            value: null,
                        },
                    ].concat(column.options)
                return column
            })
        )
    }, [props.columns])

    function formatMessage(data, verb) {
        return (
            <>
                The &ldquo;
                {data[props.titleField ? props.titleField : props.keyField]}
                &rdquo; {props.itemTitle} was {verb}.
            </>
        )
    }

    function refreshData() {
        setDataIndex(dataIndex + 1)
    }

    function onAddClick(e) {
        e.preventDefault()
        setShowForm(true)
    }

    async function onDelete(idValue) {
        const row = data.find((r) => {
            return r[props.keyField] == idValue
        })
        const result = await httpDelete(
            fetchMethod,
            props.itemPath + '/' + idValue
        )
        if (result.success === true) {
            setSuccessMessage(formatMessage(row, 'deleted'))
            refreshData()
        } else {
            setErrorMessage(result.data)
        }
    }

    async function onCreate(row, errorCallback) {
        const result = await httpPost(fetchMethod, props.itemPath, row)
        if (result.success === true) {
            refreshData()
            setShowForm(false)
            setSuccessMessage(formatMessage(row, 'added'))
        } else {
            let invalidFields = []
            let message = result.data
            if (
                props.errorStrings &&
                props.errorStrings[result.data] !== undefined
            ) {
                message = props.errorStrings[result.data].message
                invalidFields.push(props.errorStrings[result.data].column)
            }
            errorCallback(message, invalidFields)
        }
    }

    async function onUpdate(idValue, updatedRow) {
        const row = data.find((e) => {
            return e[props.keyField] == idValue
        })
        const patchValue = compare(row, updatedRow)
        const result = await httpPatch(
            fetchMethod,
            props.itemPath + '/' + idValue,
            patchValue
        )
        if (result.success === true) {
            setSuccessMessage(formatMessage(row, 'updated'))
            refreshData()
        } else {
            setErrorMessage(result.data)
        }
    }

    return (
        <>
            <CRUDIndex
                breadcrumbItems={[
                    { title: 'Admin' },
                    {
                        title: props.itemsTitle,
                        path: props.itemPath,
                    },
                ]}
                columns={columns}
                data={data}
                errorMessage={errorMessage}
                keyField={props.keyField}
                successMessage={successMessage}
                addClickCallback={() => {
                    setShowForm(true)
                }}
                deleteCallback={onDelete}
                updateCallback={onUpdate}
                validationCallback={props.validationCallback}
            />
            {showForm === true && (
                <ModalForm
                    {...props}
                    close={() => {
                        setShowForm(false)
                    }}
                    createCallback={onCreate}
                />
            )}
        </>
    )
}
