import opensearchpy

from imbi import errors
from imbi.endpoints import base


class RequestHandler(base.AuthenticatedRequestHandler):

    async def post(self, index: str):
        self.logger.debug('Request body: %r', self.get_request_body())
        try:
            result = await self.application.opensearch.client.search(
                index=index, body=self.get_request_body())
        except opensearchpy.RequestError as err:
            if err.status_code == 400:
                raise errors.BadRequest(
                    'OpenSearch request error', detail=err.info)
        self.send_response(result)
