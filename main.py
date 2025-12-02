from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import re, os, json

app = FastAPI(
    title="Autocomplete API",
    docs_url="/swagger",           # Swagger UI
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


# staged suggestion lists
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

# simplified city lists (example); replace or load as needed
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

# people options
PEOPLE = [
    {"display": "1 adult", "type": "people"},
    {"display": "2 adults", "type": "people"},
    {"display": "1 child", "type": "people"},
    {"display": "2 adults 1 child", "type": "people"},
]

# seat preferences
SEATS = [
    {"display": "Window", "type": "seat"},
    {"display": "Aisle", "type": "seat"},
    {"display": "Middle", "type": "seat"},
    {"display": "Any", "type": "seat"},
]

# meal preferences
MEALS = [
    {"display": "Vegetarian", "type": "meal"},
    {"display": "Non-vegetarian", "type": "meal"},
    {"display": "Vegan", "type": "meal"},
    {"display": "Kosher", "type": "meal"},
    {"display": "Halal", "type": "meal"},
    {"display": "No preference", "type": "meal"},
]


DEFAULT_LIMIT = 1  # internal default when we want a single suggestion by default


def norm(s: str) -> str:
    return s.strip().lower()


def find_matching_list(query_token: str, candidates: List[dict], prefer_all=False) -> List[dict]:
    """
    Return candidates that start with token, or all candidates if token is empty or no matches.
    If prefer_all=True, always return full candidates list (for steps where we want multiple choices).
    """
    if prefer_all:
        # still apply prefix filtering to order if token present
        if not query_token:
            return candidates
        token = query_token.lower()
        pref = [c for c in candidates if norm(c["display"]).startswith(token)]
        return pref if pref else candidates

    if not query_token:
        # default behavior: return only a small default set for empty token
        return candidates[: max(len(candidates), DEFAULT_LIMIT)]
    token = query_token.lower()
    filtered = [c for c in candidates if norm(c["display"]).startswith(token)]
    return filtered if filtered else candidates


@app.get("/autocomplete", response_model=List[Suggestion])
def autocomplete(q: Optional[str] = Query("", description="Query string")):
    """
    Staged autocomplete flow (no 'limit' query param exposed in swagger):

    - empty -> INITIAL_PHRASES (show 3 starters)
    - after starter -> SERVICES (flight/hotel)
    - after 'flight' present & no 'from' -> suggest 'from'
    - after 'from' and no city -> suggest cities
    - after 'from <city>' and no 'to' -> suggest 'to'
    - after 'to' and no destination -> suggest cities (destinations)
    - after destination selected -> suggest number of people (default: '1 adult')
    - after people selected -> suggest seat preferences
    - after seat selected -> suggest meal preferences
    """

    raw = (q or "")
    q_stripped = raw.strip()
    q_lower = q_stripped.lower()

    # current token: last run of non-space characters (empty if trailing space)
    m = re.search(r"(\S+)\s*$", raw)
    current_token = m.group(1) if m else ""
    if raw.endswith(" "):
        # trailing space means the user finished the token — treat as empty token for next suggestions
        current_token = ""

    # 1) if nothing typed -> show initial starters (all 3)
    if not q_stripped:
        return [Suggestion(**d) for d in INITIAL_PHRASES]

    # Helper flags
    has_flight = "flight" in q_lower
    has_hotel = "hotel" in q_lower
    has_from = re.search(r"\bfrom\b", q_lower) is not None
    has_to = re.search(r"\bto\b", q_lower) is not None

    # ---------- Stage: after starter -> services ----------
    starters = ["i want to book a", "book me a", "find me a"]
    if any(q_lower.startswith(s) for s in starters):
        # offer both services (flight, hotel) — show both so user can choose
        if not has_flight and not has_hotel:
            return [Suggestion(**d) for d in find_matching_list(current_token, SERVICES, prefer_all=True)]

    # ---------- Stage: when flight selected -> suggest 'from' if not yet present ----------
    if has_flight and not has_from:
        return [Suggestion(**d) for d in find_matching_list(current_token, [{"display": "from", "type": "connector"}])]

    # ---------- Stage: after 'from' -> suggest cities ----------
    if has_from:
        # what is after 'from'?
        after_from = re.split(r"\bfrom\b", q_lower, maxsplit=1)[1].strip()
        # if nothing typed after 'from' or the current token equals what's after_from, suggest cities
        if not after_from or (current_token and after_from == current_token.lower()):
            # for cities we usually want multiple choices shown (prefer_all=True)
            return [Suggestion(**d) for d in find_matching_list(current_token, CITIES, prefer_all=True)]

        # if a city is present after 'from' and 'to' is not yet present -> suggest 'to'
        if after_from and not has_to:
            return [Suggestion(**d) for d in find_matching_list(current_token, [{"display": "to", "type": "connector"}])]

    # ---------- Stage: after 'to' -> destination cities ----------
    if has_to:
        after_to = re.split(r"\bto\b", q_lower, maxsplit=1)[1].strip()
        if not after_to or (current_token and after_to == current_token.lower()):
            # show city options for destination
            return [Suggestion(**d) for d in find_matching_list(current_token, CITIES, prefer_all=True)]

        # destination present and user finished destination (i.e. there is some dest text and token is empty)
        # => next stage is number of people
        # detect presence of a people spec (simple heuristics)
    # ---------- Stage: after destination chosen -> suggest people ----------
    # Consider we've selected destination if both 'from' and 'to' appear and there's a non-empty token after 'to'
    has_destination = False
    if has_from and has_to:
        after_to = re.split(r"\bto\b", q_lower, maxsplit=1)[1].strip()
        if after_to:
            # a destination token exists (may be multi-word); treat as destination selected
            has_destination = True

    if has_destination and not re.search(r"\b(adult|adults|child|children)\b", q_lower):
        # user hasn't selected number of people yet; suggest PEOPLE (default '1 adult' first)
        # return full people list to let them choose, but we prefer '1 adult' as the first suggestion
        return [Suggestion(**d) for d in find_matching_list(current_token, PEOPLE, prefer_all=True)]

    # ---------- Stage: after people selected -> suggest seat prefs ----------
    if re.search(r"\b(adult|adults|child|children)\b", q_lower) and not re.search(r"\b(window|aisle|middle|any)\b", q_lower):
        # suggest seat preferences
        return [Suggestion(**d) for d in find_matching_list(current_token, SEATS, prefer_all=True)]

    # ---------- Stage: after seat selected -> suggest meal prefs ----------
    if re.search(r"\b(window|aisle|middle|any)\b", q_lower) and not re.search(r"\b(vegetarian|non-vegetarian|vegan|kosher|halal|no preference)\b", q_lower):
        return [Suggestion(**d) for d in find_matching_list(current_token, MEALS, prefer_all=True)]

    # Fallback: if none of the staged rules matched, return service + city hints (small set).
    fallback = SERVICES + CITIES
    return [Suggestion(**d) for d in find_matching_list(current_token, fallback)]
