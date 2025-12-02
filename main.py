from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import re, os, json

app = FastAPI(
    title="Autocomplete API",
    docs_url="/swagger",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Suggestion(BaseModel):
    display: str
    type: Optional[str] = None


# small curated lists used for the flow
INITIAL_PHRASES = [
    {"display": "I want to book a", "type": "starter"},
    {"display": "Book me a", "type": "starter"},
    {"display": "Find me a", "type": "starter"},
]

SERVICES = [
    {"display": "flight", "type": "service"},
    {"display": "hotel", "type": "service"},
]

CONNECTORS = [
    {"display": "from", "type": "connector"},
    {"display": "to", "type": "connector"},
]

# example city lists — extend as you like or load from a file
CITIES = [
    {"display": "Chhatrapati Shivaji Maharaj International Airport, Mumbai (BOM)", "type": "city"},
    {"display": "Indira Gandhi International Airport, New Delhi (DEL)", "type": "city"},
    {"display": "Kempegowda International Airport, Bengaluru (BLR)", "type": "city"},
    {"display": "Chennai International Airport, Chennai (MAA)", "type": "city"},
    # {"display": "Hyderabad", "type": "city"},
    # {"display": "Kolkata", "type": "city"},
    # {"display": "Pune", "type": "city"},
    {"display": "Goa Dabolim International Airport, Goa (GOI)", "type": "city"},
]

# helper normalizer
def norm(s: str) -> str:
    return s.strip().lower()


def starts_with_token(item_display: str, token: str) -> bool:
    return norm(item_display).startswith(norm(token))


def find_matching_list(query_token: str, candidates: List[dict]) -> List[dict]:
    """Return candidates that start with token, or all candidates if token empty or no matches"""
    if not query_token:
        return candidates
    token = query_token.lower()
    filtered = [c for c in candidates if norm(c["display"]).startswith(token)]
    return filtered if filtered else candidates


@app.get("/autocomplete", response_model=List[Suggestion])
def autocomplete(q: Optional[str] = Query("", description="Query string"), limit: int = Query(10, ge=1, le=50)):
    """
    Rule-based staged suggestions:
      - empty -> INITIAL_PHRASES
      - after starter phrase (I want to book a / Book me a / Find me a) -> SERVICES (flight/hotel)
      - after `flight` present but no `from` -> suggest `from`
      - after `from` but no city -> city list
      - after `from <city>` but no `to` -> suggest `to`
      - after `to` but no destination city -> destination city list
    Prefix-matching is performed on the current token.
    """

    raw = (q or "")
    q_stripped = raw.strip()
    q_lower = q_stripped.lower()

    # token user is currently typing = last run of non-space characters (empty if trailing space)
    # e.g. "I want to book a f" -> token 'f'
    m = re.search(r"(\S+)\s*$", raw)
    current_token = m.group(1) if m else ""
    # if raw ends with a space, we want empty current token (new token)
    if raw.endswith(" "):
        current_token = ""

    # 1) if nothing typed -> show initial starters
    if not q_stripped:
        return INITIAL_PHRASES[:limit]

    # 2) if user started one of the starter phrases, offer services (flight/hotel) if not present
    starters = ["i want to book a", "book me a", "find me a"]
    if any(q_lower.startswith(s) for s in starters):
        # if neither flight nor hotel present, suggest services
        if "flight" not in q_lower and "hotel" not in q_lower:
            return find_matching_list(current_token, SERVICES)[:limit]

    # 3) if sentence contains 'flight' and 'from' not present -> suggest 'from'
    if "flight" in q_lower and "from" not in q_lower:
        return find_matching_list(current_token, [{"display": "from", "type": "connector"}])[:limit]

    # 4) if sentence has 'from' but no city after it -> suggest city list
    #    detect pattern 'from' not followed by a non-space token (or followed by token equal to current_token)
    if re.search(r"\bfrom\b", q_lower):
        # extract substring after 'from'
        after_from = re.split(r"\bfrom\b", q_lower, maxsplit=1)[1].strip()
        # if nothing after from or after_from equals current_token => suggest city
        if not after_from or (current_token and after_from == current_token.lower()):
            return find_matching_list(current_token, CITIES)[:limit]
        # otherwise we've got a city after 'from' -> proceed to suggest 'to' if not present
        if "to" not in q_lower:
            return find_matching_list(current_token, [{"display": "to", "type": "connector"}])[:limit]

    # 5) if sentence contains 'to' but no destination city after it -> suggest city list (destinations)
    if re.search(r"\bto\b", q_lower):
        after_to = re.split(r"\bto\b", q_lower, maxsplit=1)[1].strip()
        if not after_to or (current_token and after_to == current_token.lower()):
            return find_matching_list(current_token, CITIES)[:limit]

    # Fallback: if none of the above, fall back to small default suggestions (services)
    # You can expand this to a fuzzy search over a larger dataset.
    return find_matching_list(current_token, SERVICES + CITIES)[:limit]
