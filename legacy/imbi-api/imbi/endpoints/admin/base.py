"""
Base Admin Request Handlers

"""
from imbi.endpoints import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    @base.require_permission('admin')
    async def delete(self, *args, **kwargs):
        await super().delete(*args, **kwargs)

    @base.require_permission('admin')
    async def get(self, *args, **kwargs):
        await super().get(*args, **kwargs)

    @base.require_permission('admin')
    async def patch(self, *args, **kwargs):
        await super().patch(*args, **kwargs)

    @base.require_permission('admin')
    async def post(self, *args, **kwargs):
        await super().post(*args, **kwargs)
