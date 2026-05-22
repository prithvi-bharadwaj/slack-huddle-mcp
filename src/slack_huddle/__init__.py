"""slack-huddle-mcp — expose Slack AI huddle transcripts to MCP-compatible LLM agents."""

from slack_huddle.api import (
    AuthError,
    RateLimitError,
    SlackApiError,
    SlackHuddleClient,
)
from slack_huddle.parser import (
    SpeakerTurn,
    format_lines,
    format_markdown,
    parse_transcription,
)

__version__ = "0.3.0"

__all__ = [
    "AuthError",
    "RateLimitError",
    "SlackApiError",
    "SlackHuddleClient",
    "SpeakerTurn",
    "__version__",
    "format_lines",
    "format_markdown",
    "parse_transcription",
]
