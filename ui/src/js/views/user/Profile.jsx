import React from 'react'
import {useTranslation} from 'react-i18next'
import {Link} from '@reach/router'

import {UserContext} from '../../contexts'

const Profile = () => {
  const {t} = useTranslation()
  return (
    <UserContext.Consumer>
      {(user) => (
        <dl className="row profile">
          <dt className="col-sm-2">{t('common.displayName')}</dt>
          <dd className="col-sm-10">{user.display_name}</dd>
          <dt className="col-sm-2">{t('common.userName')}</dt>
          <dd className="col-sm-10">{user.username}</dd>
          <dt className="col-sm-2">{t('common.userType')}</dt>
          <dd className="col-sm-10">{user.user_type}</dd>
          {user.user_type != 'internal' && (
            <dt className="col-sm-2">
              {t('common.externalId')}
            </dt>
          )}
          {user.user_type != 'internal' && (
            <dd className="col-sm-10">{user.external_id}</dd>
          )}
          <dt className="col-sm-2">{t('common.emailAddress')}</dt>
          <dd className="col-sm-10">{user.email_address}</dd>
          <dt className="col-sm-2">
            {t('common.displayName')} {t('common.groups')}
          </dt>
          <dd className="col-sm-10 groups">
            <RenderGroups groups={user.groups}/>
          </dd>
        </dl>
      )}
    </UserContext.Consumer>
  )
}

const RenderGroups = (props) => {
  const listItems = props.groups.map((group) => {
    return (
      <li key={group.name} className="list-inline-item">
        <Link
          className="badge badge-primary"
          to={'/admin/groups#' + group.name}
        >
          {group.name}
        </Link>
      </li>
    )
  })
  return <ul className="list-unstyled">{listItems}</ul>
}

export {Profile}
