from imbi.endpoints import base


class GroupsRequestHandler(base.CRUDRequestHandler):

    NAME = 'ui-groups'

    GET_SQL = 'SELECT name FROM v1.groups ORDER BY name ASC;'
    TTL = 300
