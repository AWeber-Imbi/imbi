import re
import uuid

import ulid
from tornado import web

from . import base


class RequestHandler(base.ValidatingRequestHandler):

    NAME = 'authentication-tokens'

    CREATE_SQL = re.sub(r'\s+', ' ', """
        INSERT INTO v1.authentication_tokens (token, "name", username)
             VALUES (%(token)s, %(name)s, %(username)s)
          RETURNING username, token, "name",
                    created_at, expires_at, last_used_at
        """)

    DELETE_SQL = re.sub(r'\s+', ' ', """
        DELETE FROM v1.authentication_tokens
              WHERE username = %(username)s
                AND token = %(token)s""")

    GET_SQL = re.sub(r'\s+', ' ', """
        SELECT token, "name", username, created_at, expires_at, last_used_at
          FROM v1.authentication_tokens
         WHERE username = %(username)s
         ORDER BY created_at""")

    async def delete(self, token):
        result = await self.postgres_execute(self.DELETE_SQL, {
            'token': token,
            'username': self.current_user.username
        }, 'delete-authentication-token')
        if not result.row_count:
            raise web.HTTPError(404, reason='Item not found')
        self.set_status(204, reason='Item Deleted')

    async def get(self):
        result = await self.postgres_execute(
            self.GET_SQL, {'username': self.current_user.username},
            'get-authentication-tokens')
        self.send_response(result.rows)

    async def post(self):
        values = self.get_request_body()
        values.update({
            'token': uuid.UUID(ulid.ULID().hex),
            'username': self.current_user.username
        })
        result = await self.postgres_execute(
            self.CREATE_SQL, values, 'create-authentication-token')
        self.send_response(result.row)
