import {Link} from '@reach/router'
import React, {Fragment, useContext} from 'react'
import PropTypes from "prop-types";
import {useTranslation} from 'react-i18next'

import {UserContext} from '../../contexts'

function Groups({groups}) {
  return (
    <Fragment>{groups.map((group) => {
      return (
        <Link className="inline-flex items-center px-2.5 py-0.5 mr-2 rounded-full text-xs font-medium bg-blue-700 text-white"
              key={group.name}
              to={'/ui/admin/groups#' + group.name}>
          {group.name}
        </Link>
      )
    })}
  </Fragment>)
}
Groups.propTypes = {
  groups: PropTypes.array
}

const Item = ({label, value, children}) => {
  return (
    <div className="px-4 py-2 sm:grid sm:grid-cols-3 sm:gap-4 sm:px-6">
      <dt className="text-sm font-medium text-gray-500">{label}</dt>
      <dd className="mt-1 text-sm text-gray-900 sm:mt-0 sm:col-span-2">
        {value !== undefined && value}
        {children !== undefined && children}
      </dd>
    </div>
  )
}
Item.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.string,
  children: PropTypes.node
}

function Profile() {
  const {t} = useTranslation()
  const user = useContext(UserContext)
  return (
    <div className="container mx-auto my-auto max-w-4xl pb-0 bg-white shadow overflow-hidden sm:rounded-lg">
      <div className="px-4 py-5 sm:px-6">
        <h3 className="text-lg leading-6 font-medium text-gray-900">
          User Profile
        </h3>
      </div>
      <div className="bg-gray-50 border-t border-gray-200 py-5">
        <dl>
          <Item label={t('profile.displayName')} value={user.display_name} />
          <Item label={t('profile.userName')} value={user.username} />
          <Item label={t('profile.userType')} value={user.user_type} />
          {user.user_type !== 'internal' && (
            <Item label={t('profile.externalId')} value={user.external_id} />
          )}
          <Item label={t('profile.emailAddress')} value={user.email_address} />
          <Item label={t('profile.groups')}>
            <Groups groups={user.groups} />
          </Item>
        </dl>
      </div>
    </div>
  )
}

export {Profile}
