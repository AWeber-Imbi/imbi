"""Domain and API models for the AI assistant."""

import datetime
import typing
import uuid

import pydantic

# --- Domain models (stored in Neo4j) ---


class Conversation(pydantic.BaseModel):
    """AI assistant conversation."""

    model_config = pydantic.ConfigDict(extra='ignore')

    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    user_email: str
    title: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    model: str
    is_archived: bool = False


class Message(pydantic.BaseModel):
    """AI assistant conversation message."""

    model_config = pydantic.ConfigDict(extra='ignore')

    id: str = pydantic.Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    role: typing.Literal['user', 'assistant']
    content: str
    tool_use: list[dict[str, typing.Any]] | None = None
    tool_results: list[dict[str, typing.Any]] | None = None
    created_at: datetime.datetime
    sequence: int
    token_usage: dict[str, int] | None = None


# --- Request models ---


class CreateConversationRequest(pydantic.BaseModel):
    """Request body for creating a new conversation."""

    model: str | None = None


class SendMessageRequest(pydantic.BaseModel):
    """Request body for sending a message."""

    content: str = pydantic.Field(min_length=1, max_length=32768)


class UpdateConversationRequest(pydantic.BaseModel):
    """Request body for updating a conversation."""

    title: str | None = None
    is_archived: bool | None = None


# --- Response models ---


class ConversationResponse(pydantic.BaseModel):
    """Response model for a conversation."""

    id: str
    user_email: str
    title: str | None
    created_at: str
    updated_at: str
    model: str
    is_archived: bool


class MessageResponse(pydantic.BaseModel):
    """Response model for a message."""

    id: str
    conversation_id: str
    role: typing.Literal['user', 'assistant']
    content: str
    tool_use: list[dict[str, typing.Any]] | None = None
    tool_results: list[dict[str, typing.Any]] | None = None
    created_at: str
    sequence: int
    token_usage: dict[str, int] | None = None


class ConversationWithMessagesResponse(ConversationResponse):
    """Response model for a conversation with messages."""

    messages: list[MessageResponse]


# --- Converters ---


def conversation_to_response(
    conv: Conversation,
) -> ConversationResponse:
    """Convert a Conversation model to a response."""
    return ConversationResponse(
        id=conv.id,
        user_email=conv.user_email,
        title=conv.title,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
        model=conv.model,
        is_archived=conv.is_archived,
    )


def message_to_response(
    msg: Message,
) -> MessageResponse:
    """Convert a Message model to a response."""
    return MessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        role=msg.role,
        content=msg.content,
        tool_use=msg.tool_use,
        tool_results=msg.tool_results,
        created_at=msg.created_at.isoformat(),
        sequence=msg.sequence,
        token_usage=msg.token_usage,
    )
