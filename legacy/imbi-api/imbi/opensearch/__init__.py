"""
Modules for interacting with and materializing data for OpenSearch Indexes
"""
import asyncio
import typing

import sprockets.mixins.mediatype.content
import sprockets_postgres
import tornado.web

from imbi import errors


class SupportsIndexDocumentById(typing.Protocol):
    async def index_document_by_id(self, doc_id: int) -> bool:
        ...


class SearchIndexRequestHandler(
        sprockets_postgres.RequestHandlerMixin,
        sprockets.mixins.mediatype.content.ContentMixin,
        tornado.web.RequestHandler,
):
    search_index: SupportsIndexDocumentById
    SQL: typing.ClassVar[str] = ''

    async def prepare(self) -> None:
        maybe_coro = super().prepare()
        if asyncio.isfuture(maybe_coro) or asyncio.iscoroutine(maybe_coro):
            await maybe_coro
        if not self.SQL:
            raise errors.InternalServerError(
                'Programming error in %s: SQL is not defined',
                self.__class__.__name__,
                reason='Internal Server Error',
                title='Programming Error',
                detail='SQL is not defined',
                source=self.__class__.__name__,
            )
        if getattr(self, 'search_index', None) is None:
            raise errors.InternalServerError(
                'Programming error in %s: search_index is None',
                self.__class__.__name__,
                reason='Internal Server Error',
                title='Programming Error',
                detail='search_index is None',
                source=self.__class__.__name__,
            )

    async def post(self) -> None:
        docs_to_index: list[int] = []
        if ids := self.get_query_arguments('id'):
            try:
                docs_to_index.extend(int(arg) for arg in ids)
            except ValueError:
                raise errors.BadRequest('Invalid ID found in %r', ids)
        else:
            docs_to_index.extend(
                r['id'] for r in await self.postgres_execute(self.SQL))

        indexed_documents = 0
        for doc_id in docs_to_index:
            if await self.search_index.index_document_by_id(doc_id):
                indexed_documents += 1

        self.send_response({
            'status': 'ok',
            'message': f'Queued {indexed_documents} documents for indexing'
        })
