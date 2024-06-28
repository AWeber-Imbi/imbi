import typing

import pydantic


class Param(pydantic.BaseModel):
    type: typing.Literal['String', 'SecureString', 'StringList']
    value: str


class EnvironmentFieldMixin:
    @pydantic.computed_field
    @property
    def environment(self) -> str:
        return self.path.split('/')[1]


class RemovePatch(pydantic.BaseModel, EnvironmentFieldMixin):
    op: typing.Literal['remove']
    path: str

    @pydantic.field_validator('path', mode='after')
    def validate_path(cls, value: str, info: pydantic.ValidationInfo):
        if value.count('/') > 1:
            raise ValueError(
                f'Invalid path: {value}. Can only remove an environment')

        environments = info.context.get('environments', [])
        environment = value.split('/')[1]
        if environment not in environments:
            raise ValueError(
                f'Invalid environment "{environment}", must be one of: '
                f'{environments}')

        return value


class ReplacePatch(pydantic.BaseModel, EnvironmentFieldMixin):
    op: typing.Literal['replace']
    path: str
    value: str

    @pydantic.computed_field
    @property
    def type(self) -> str:
        return self.path.split('/')[2]

    @pydantic.model_validator(mode='after')
    def validate_replace(self, info: pydantic.ValidationInfo):
        environments = info.context.get('environments', [])

        if self.path.count('/') != 2:
            raise ValueError(
                f'Invalid path: {self.value}. Must replace type or value at '
                'an environment')

        _, environment, update_type = self.path.split('/')
        if environment not in environments:
            raise ValueError(
                f'Invalid environment "{environment}", must be one of: '
                f'{environments}')

        if update_type not in {'type', 'value'}:
            raise ValueError(
                f'Invalid update for "{update_type}", must be either "type" '
                'or "value"')

        if update_type == 'type' and self.value not in {
                'String', 'SecureString', 'StringList'
        }:
            raise ValueError(
                'Invalid SSM type update: value must be one of "String", '
                f'"StringList", or "SecureString", got {self.value}')

        return self


class AddPatch(pydantic.BaseModel, EnvironmentFieldMixin):
    op: typing.Literal['add']
    path: str
    value: Param

    @pydantic.field_validator('path')
    @classmethod
    def validate_path(cls, value: str, info: pydantic.ValidationInfo):
        if value.count('/') > 1:
            raise ValueError(
                f'Invalid path: {value}. Can only add at an environment')

        environments = info.context.get('environments', [])
        environment = value.split('/')[1]
        if environment not in environments:
            raise ValueError(
                f'Invalid environment "{environment}", must be one of: '
                f'{environments}')

        return value


SSMPatch = typing.Annotated[typing.Union[RemovePatch, ReplacePatch, AddPatch],
                            pydantic.Field(..., discriminator='op')]


class SSMPatchBody(pydantic.RootModel):
    root: list[SSMPatch]

    def __iter__(self):
        return iter(self.root)

    def __getitem__(self, item):
        return self.root[item]
