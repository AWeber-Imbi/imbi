import PropTypes from "prop-types"
import React from 'react'
import {useTranslation} from "react-i18next";

import {Columns} from "../../schema"

import {default as HeadColumn} from "./HeadColumn"

function Head({columns, includeEdit}) {
  const {t} = useTranslation()
  return (
    <thead className="bg-gray-50">
      <tr>
        {columns.map((column) => {
          if (column.tableOptions === undefined || column.tableOptions.hide !== true)
            return (
              <HeadColumn column={column} key={"column-" + column.name} />
            )
        })}
        {includeEdit === true && (
          <HeadColumn key="column-edit" className="w-24" srOnly={true}>{t("common.edit")}</HeadColumn>
        )}
      </tr>
    </thead>
  )
}
Head.defaultProps = {
  includeEdit: false
}

Head.propTypes = {
  columns: Columns,
  includeEdit: PropTypes.bool
}

export default Head
