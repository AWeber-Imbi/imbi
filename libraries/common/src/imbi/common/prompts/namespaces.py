"""The prompt CMS namespaces whose prompts are skills.

This module imports nothing, so imbi-mcp (which has no graph
dependencies) and imbi-api share one definition.
"""

#: Skills that the Slack bot and the assistant load on demand.
SKILLS = 'imbi-skills'

#: Skills that imbi-mcp serves to MCP clients.
MCP_SKILLS = 'mcp-skills'

#: A skill's name and description reach every consumer's model, so
#: changing them needs prompt:promote in these namespaces.
SKILL_NAMESPACES = frozenset({SKILLS, MCP_SKILLS})
