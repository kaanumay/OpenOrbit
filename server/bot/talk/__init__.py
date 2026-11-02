"""Normal mode chat engine: bots that read what is said and answer like people (see dialog.py). The LLM mode uses it as its fallback."""
from .dialog import on_human, heard_bot, spontaneous, event_line, witness, say, state, private, help_reply     # noqa: F401
