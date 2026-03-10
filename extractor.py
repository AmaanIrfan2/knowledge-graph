import json
import logging
import os

from google import genai
from google.genai import types
import tiktoken

logger = logging.getLogger(__name__)

_PROMPT = """\
You are an expert entity and relation extraction system. Your output will be used to construct a formal Knowledge Graph (Neo4j) connecting global entities, organizations, and events based on news articles.

Given the article text below, extract:

1. ELEMENTS (Nodes) — every distinct, important entity mentioned in the article.
   Each element must have:
   - "name": the canonical, globally recognizable name (e.g. "Narendra Modi", not "the PM" or "Modi". "United Nations", not "the UN").
   - "entity_type": exactly one of: PERSON, ORGANIZATION, LOCATION, COUNTRY, COMPANY, EVENT.

2. RELATIONS (Edges) — the factual relationships between the extracted elements.
   Each relation must have:
   - "subject": the name of the subject element (must match an element name exactly).
   - "relation": a standardized, uppercase, snake_case string representing the relationship (e.g., "VISITED", "ACQUIRED", "HEADQUARTERED_IN", "APPOINTED_BY", "LOCATED_IN"). Do NOT use specific conversational phrases. Make them broad and reusable.
   - "object": the name of the object element (must match an element name exactly).

Rules:
- Knowledge Graph Context: Think about how these nodes and edges will look on a graph. Avoid creating orphaned nodes that have no edges unless the entity is the central subject of the article.
- Deduplicate stringently: Resolve coreferences. If the same person/place/org is mentioned multiple ways, extract them ONLY ONCE using their canonical name.
- Directionality matters: A relation of `subject: Apple`, `relation: ACQUIRED`, `object: Beats` is completely different from the reverse.
- Relations MUST only reference elements you have explicitly extracted in the "elements" list.
- Return valid JSON only, no markdown, no explanation.

Article text:
\"\"\"
{body_text}
\"\"\"

Respond with this exact JSON structure:
{{
  "elements": [{{ "name": "...", "entity_type": "..." }}],
  "relations": [{{ "subject": "...", "relation": "...", "object": "..." }}]
}}
"""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "entity_type": {
                        "type": "string",
                        "enum": ["PERSON", "ORGANIZATION", "LOCATION", "COUNTRY", "COMPANY", "EVENT"],
                    },
                },
                "required": ["name", "entity_type"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "relation": {"type": "string"},
                    "object": {"type": "string"},
                },
                "required": ["subject", "relation", "object"],
            },
        },
    },
    "required": ["elements", "relations"],
}

_tokenizer = tiktoken.get_encoding("cl100k_base")
_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "8000"))


def _truncate(text: str) -> str:
    tokens = _tokenizer.encode(text)
    if len(tokens) <= _MAX_TOKENS:
        return text
    logger.warning("Truncating body text from %d to %d tokens", len(tokens), _MAX_TOKENS)
    return _tokenizer.decode(tokens[:_MAX_TOKENS])


async def extract(body_text: str) -> tuple[list[dict], list[dict]]:
    """
    Call Gemini to extract entities and relations.
    Returns (elements, relations).
    """
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    
    prompt = _PROMPT.format(body_text=_truncate(body_text))
    
    response = await client.aio.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview"),
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_RESPONSE_SCHEMA,
            temperature=0.0,
        )
    )
    result = json.loads(response.text)

    return result.get("elements", []), result.get("relations", [])
