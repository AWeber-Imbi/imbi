"""
Modules for interacting with and materializing data for OpenSearch Indexes
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import typing

import sprockets.mixins.mediatype.content
import sprockets_postgres
import tornado.web

from imbi import errors
if typing.TYPE_CHECKING:
    from imbi import app

ModelType = typing.TypeVar('ModelType')


class SupportsIndexDocumentById(typing.Protocol):
    async def index_document_by_id(self, doc_id: int) -> bool:
        ...


class SearchIndex(typing.Generic[ModelType]):
    INDEX: typing.ClassVar[str] = ''

    def __init__(
        self, application: 'app.Application',
        fetch_method: typing.Callable[[int, 'app.Application'],
                                      typing.Awaitable[ModelType]]
    ) -> None:
        super().__init__()
        self.application = application
        self.fetch_document_by_id = fetch_method
        self.logger = logging.getLogger(__name__).getChild(
            self.__class__.__name__)

    async def create_index(self) -> None:
        await self.application.opensearch.create_index(self.INDEX)

    async def create_mapping(self) -> None:
        await self.application.opensearch.create_mapping(
            self.INDEX, await self._build_mappings())

    async def delete_document(self, doc_id: int | str) -> None:
        await self.application.opensearch.delete_document(
            self.INDEX, str(doc_id))

    async def index_document(self, doc: ModelType) -> None:
        await self.application.opensearch.index_document(
            self.INDEX, str(doc.id), self._serialize_document(doc), True)

    async def index_document_by_id(self, doc_id: int) -> bool:
        doc = None
        with contextlib.suppress(errors.DatabaseError):
            doc = await self.fetch_document_by_id(doc_id, self.application)
        if doc is None:
            self.logger.warning('Document not found for %s while indexing',
                                doc_id)
            return False
        await self.index_document(doc)
        return True

    async def search(self,
                     query: str,
                     max_results: int = 1000) -> dict[str, list[dict]]:
        return await self.application.opensearch.search(
            self.INDEX, query, max_results)

    async def _build_mappings(self):
        raise NotImplementedError()

    def _serialize_document(self, doc: ModelType) -> dict[str, typing.Any]:
        raise NotImplementedError()


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
