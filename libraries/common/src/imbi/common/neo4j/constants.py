"""Constants for the Neo4J integration."""

_EMBEDDING_INDEX_CONFIG = """\
{
    `vector.dimensions`: 1536,
    `vector.similarity_function`: 'cosine'
}
"""

INDEXES: list[str] = [
    # Blueprints
    'CREATE CONSTRAINT blueprint_pkey IF NOT EXISTS FOR (n:Blueprint) '
    'REQUIRE (n.name, n.type) IS UNIQUE;',
    # Teams
    'CREATE CONSTRAINT team_slug_unique IF NOT EXISTS FOR (n:Team) '
    'REQUIRE n.slug IS UNIQUE;',
    # AI Assistant Conversations
    'CREATE CONSTRAINT conversation_id_unique IF NOT EXISTS '
    'FOR (n:Conversation) REQUIRE n.id IS UNIQUE;',
    'CREATE INDEX conversation_user_email IF NOT EXISTS '
    'FOR (n:Conversation) ON (n.user_email);',
    'CREATE INDEX conversation_updated_at IF NOT EXISTS '
    'FOR (n:Conversation) ON (n.updated_at);',
    # AI Assistant Messages
    'CREATE CONSTRAINT message_id_unique IF NOT EXISTS '
    'FOR (n:Message) REQUIRE n.id IS UNIQUE;',
    'CREATE INDEX message_conversation_id IF NOT EXISTS '
    'FOR (n:Message) ON (n.conversation_id);',
]
