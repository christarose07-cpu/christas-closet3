"""
Christa's Closet – an outfit recommendation and packing list web app.

This FastAPI application provides a simple web interface for generating daily
outfit suggestions from a capsule wardrobe, rating those outfits, viewing a
history of past looks, and assembling a packing list for multi‑day trips.  It
also exposes a manifest and service worker so the app can be installed on an
iPhone as a progressive web app (PWA).  To launch the app locally run:

    uvicorn main:app --host 0.0.0.0 --port 8000

Once running in this environment the app can be accessed via
``http://terminal.local:8000``.

The capsule wardrobe and outfit generation logic live inside this file.  The
overall aesthetic is kept deliberately playful and uplifting to mirror the
"Pink District" look described by the user.  Ratings and history are stored
in a CSV file on disk for persistence across sessions.
"""

import csv
import json
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


# Initialise the FastAPI app
app = FastAPI(title="Christa's Closet", docs_url=None, redoc_url=None)

# Set up templating and static file serving.  Templates live in the `templates`
# folder and static assets (CSS, JS, images) live in the `static` folder.
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)

# Path to the CSV file used for persisting rating history across sessions.  If
# the file doesn't exist it will be created on first write.
RATING_FILE = BASE_DIR / "rating_history.csv"


# Define a simple capsule wardrobe.  Each item is described by its name,
# warmth (light, medium or warm), and style categories.  These tags
# allow the outfit generator to filter pieces based on the weather and the
# selected activity.
# The default capsule wardrobe.  When the app boots for the first time
# this structure is written to `wardrobe.json`.  If the file exists on
# subsequent launches, it will be loaded instead.  This allows the user
# to add and remove items without losing their changes.  Each item is
# represented by a dictionary; for clothing the keys include `name`,
# `warmth` and `style` so the generator can filter by weather and
# activity.  Accessories and activewear only require a `name` field.
DEFAULT_WARDROBE: Dict[str, List[Dict[str, str]]] = {
    "tops": [
        {"name": "white blouse", "warmth": "light", "style": "work"},
        {"name": "pink silk blouse", "warmth": "light", "style": "dressy"},
        {"name": "grey knit sweater", "warmth": "warm", "style": "casual"},
        {"name": "black turtleneck", "warmth": "warm", "style": "dressy"},
        {"name": "graphic tee", "warmth": "light", "style": "casual"},
    ],
    "bottoms": [
        {"name": "blue jeans", "warmth": "medium", "style": "casual"},
        {"name": "black trousers", "warmth": "medium", "style": "work"},
        {"name": "pink pencil skirt", "warmth": "light", "style": "work"},
        {"name": "leggings", "warmth": "light", "style": "workout"},
    ],
    "dresses": [
        {"name": "floral day dress", "warmth": "light", "style": "date"},
        {"name": "little black dress", "warmth": "light", "style": "dressy"},
        {"name": "athletic dress", "warmth": "light", "style": "workout"},
    ],
    "outerwear": [
        {"name": "denim jacket", "warmth": "light", "style": "casual"},
        {"name": "blazer", "warmth": "medium", "style": "work"},
        {"name": "trench coat", "warmth": "warm", "style": "dressy"},
    ],
    "shoes": [
        {"name": "white sneakers", "style": "casual"},
        {"name": "black heels", "style": "dressy"},
        {"name": "ankle boots", "style": "casual"},
        {"name": "running shoes", "style": "workout"},
        {"name": "ballet flats", "style": "work"},
    ],
    "accessories": [
        {"name": "gold hoop earrings"},
        {"name": "pink scarf"},
        {"name": "black leather belt"},
        {"name": "statement necklace"},
        {"name": "crossbody bag"},
    ],
    "activewear": [
        {"name": "sports bra"},
        {"name": "yoga leggings"},
    ],
}

# Paths for persisting custom wardrobe, events, ratings and settings.
WARDROBE_JSON = BASE_DIR / "wardrobe.json"
EVENTS_JSON = BASE_DIR / "events.json"
SCORES_JSON = BASE_DIR / "scores.json"
SETTINGS_JSON = BASE_DIR / "settings.json"


def load_json(path: Path, default: Optional[Dict] = None) -> Dict:
    """Load a JSON file from disk.  If the file does not exist,
    return a copy of the provided default or an empty dict.  Any
    exceptions will also return the default.
    """
    try:
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return default.copy() if isinstance(default, dict) else {}


def save_json(path: Path, data: Dict) -> None:
    """Persist a dictionary as JSON on disk."""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def init_data():
    """Initialise persistent data files if they do not already exist."""
    # Initialise wardrobe file
    if not WARDROBE_JSON.exists():
        save_json(WARDROBE_JSON, DEFAULT_WARDROBE)
    # Initialise events file
    if not EVENTS_JSON.exists():
        save_json(EVENTS_JSON, {})
    # Initialise scores file
    if not SCORES_JSON.exists():
        save_json(SCORES_JSON, {})
    # Initialise settings file with a default notification time of 08:00
    if not SETTINGS_JSON.exists():
        save_json(SETTINGS_JSON, {"notification_time": "08:00"})


# Call initialisation on module import
init_data()


def load_wardrobe() -> Dict[str, List[Dict[str, str]]]:
    """Load the current wardrobe from disk."""
    return load_json(WARDROBE_JSON, DEFAULT_WARDROBE)


def load_events() -> Dict[str, Dict[str, str]]:
    """Load saved events from disk.  Each entry is keyed by an id and
    contains `name`, `date`, `time` and `style` keys."""
    return load_json(EVENTS_JSON, {})


def load_scores() -> Dict[str, float]:
    """Load the rating scores per item.  The dictionary maps item names
    to their average rating."""
    return load_json(SCORES_JSON, {})


def save_scores(scores: Dict[str, float]) -> None:
    """Persist the scores dictionary."""
    save_json(SCORES_JSON, scores)


def load_settings() -> Dict[str, str]:
    """Load user settings (e.g. notification time)."""
    return load_json(SETTINGS_JSON, {"notification_time": "08:00"})


def save_settings(settings: Dict[str, str]) -> None:
    save_json(SETTINGS_JSON, settings)


def update_scores(outfit: Dict[str, Optional[str]], rating: int) -> None:
    """Update per‑item average ratings based on the provided rating.

    For each clothing component in the outfit (top, bottom, dress, outer,
    shoes) the function updates a running average and count stored in
    `scores.json` under the `__meta` key.  Items without prior ratings
    start from a neutral average of 3.0.  Accessories are not scored.
    """
    scores = load_scores()
    meta: Dict[str, Dict[str, float]] = scores.get("__meta", {})
    for part in ["top", "bottom", "dress", "outer", "shoes"]:
        item = outfit.get(part)
        if not item:
            continue
        info = meta.get(item, {"avg": 3.0, "count": 0})
        old_avg = info["avg"]
        count = info["count"]
        new_avg = (old_avg * count + rating) / (count + 1)
        meta[item] = {"avg": new_avg, "count": count + 1}
        scores[item] = new_avg
    scores["__meta"] = meta
    save_scores(scores)



def get_weather(latitude: float = 39.9612, longitude: float = -82.9988) -> Dict[str, float]:
    """Fetch current temperature and precipitation probability using the
    open‑meteo API.  Returns Fahrenheit temperature and precipitation chance (0–100).
    If the API call fails, reasonable defaults are returned.
    """
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast?"
            f"latitude={latitude}&longitude={longitude}"
            "&current_weather=true&hourly=precipitation_probability"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        temp_c = data["current_weather"]["temperature"]
        precip = data["hourly"]["precipitation_probability"][0]
        temp_f = temp_c * 9 / 5 + 32
        return {"temperature": temp_f, "precip": precip}
    except Exception:
        # Fallback to mild weather
        return {"temperature": 70.0, "precip": 10.0}


def choose_items(activity: str, weather: Dict[str, float]) -> Dict[str, str]:
    """Select wardrobe pieces based on activity and weather using a
    weighted random approach informed by prior ratings.

    The wardrobe is loaded from the persistent JSON file at runtime.  This
    function also references stored item scores to bias the selection
    towards pieces that have received higher average ratings, while still
    maintaining variety.

    Args:
        activity: The planned activity (Work, Casual, Workout, Date, Event, Travel).
        weather: Dictionary with 'temperature' and 'precip' values.

    Returns:
        A dictionary describing the chosen outfit.
    """
    wardrobe = load_wardrobe()
    scores = load_scores()
    meta = scores.get("__meta", {})
    temperature = weather.get("temperature", 70.0)
    precip = weather.get("precip", 0.0)
    outfit: Dict[str, Optional[str]] = {}

    def filter_by(tags: List[Dict[str, str]], warmth: Optional[str] = None, style: Optional[str] = None) -> List[Dict[str, str]]:
        candidates = []
        for item in tags:
            if warmth and item.get("warmth") and item.get("warmth") != warmth:
                continue
            if style and item.get("style") and item.get("style") != style:
                continue
            candidates.append(item)
        return candidates if candidates else tags

    def weighted_choice(items: List[Dict[str, str]]) -> Dict[str, str]:
        """Select an item biased by its rating.  Items with higher
        average ratings are more likely to be chosen.  If an item has
        never been rated it is given a neutral weight of 1.0."""
        weights = []
        for item in items:
            name = item.get("name")
            info = meta.get(name, {"avg": 3.0})
            # Add a small epsilon to avoid zero weight
            weights.append(max(info.get("avg", 3.0), 0.1))
        # Normalise weights
        total = sum(weights)
        if total == 0:
            total = 1.0
        probs = [w / total for w in weights]
        choice = random.choices(items, weights=probs, k=1)[0]
        return choice

    # Determine warmth category based on temperature
    if temperature < 55:
        warmth_pref = "warm"
    elif temperature < 70:
        warmth_pref = "medium"
    else:
        warmth_pref = "light"

    # Map activities to style tags
    style_map = {
        "Work": "work",
        "Casual": "casual",
        "Workout": "workout",
        "Date": "date",
        "Event": "dressy",
        "Travel": "casual",
    }
    style_pref = style_map.get(activity, "casual")

    # If activity is workout, use activewear and running shoes exclusively
    if activity == "Workout":
        top_item = weighted_choice(wardrobe.get("activewear", []))
        top = top_item.get("name")
        bottoms = [b for b in wardrobe.get("bottoms", []) if b.get("style") == "workout" or b.get("name") == "leggings"]
        bottom_item = weighted_choice(bottoms) if bottoms else None
        bottom = bottom_item.get("name") if bottom_item else None
        shoes_items = [s for s in wardrobe.get("shoes", []) if s.get("style") == "workout"]
        shoes_item = weighted_choice(shoes_items) if shoes_items else None
        shoes = shoes_item.get("name") if shoes_item else None
        outer = None
    else:
        # Choose top
        tops = filter_by(wardrobe.get("tops", []), warmth=warmth_pref if warmth_pref != "light" else None, style=style_pref)
        top = weighted_choice(tops).get("name") if tops else None
        # Choose bottom or dress
        dress = None
        bottom = None
        if activity in {"Date", "Event"} and random.random() < 0.6:
            dresses = filter_by(wardrobe.get("dresses", []), warmth=warmth_pref if warmth_pref != "light" else None, style=style_pref)
            if dresses:
                dress = weighted_choice(dresses).get("name")
            else:
                bottoms = filter_by(wardrobe.get("bottoms", []), warmth=warmth_pref if warmth_pref != "light" else None, style=style_pref)
                bottom = weighted_choice(bottoms).get("name") if bottoms else None
        else:
            bottoms = filter_by(wardrobe.get("bottoms", []), warmth=warmth_pref if warmth_pref != "light" else None, style=style_pref)
            bottom = weighted_choice(bottoms).get("name") if bottoms else None
        # Choose outerwear if cold or rainy
        outer = None
        if temperature < 65 or precip > 50:
            outs = filter_by(wardrobe.get("outerwear", []), warmth=warmth_pref if warmth_pref != "light" else None, style=style_pref)
            if outs:
                outer = weighted_choice(outs).get("name")
        # Choose shoes
        shoes_candidates = [s for s in wardrobe.get("shoes", []) if s.get("style") == style_pref]
        if not shoes_candidates:
            shoes_candidates = wardrobe.get("shoes", [])
        shoes_item = weighted_choice(shoes_candidates) if shoes_candidates else None
        shoes = shoes_item.get("name") if shoes_item else None
    # Choose accessories (up to 2 random pieces)
    # Choose accessories (up to 2 random pieces)
    accessories_list = wardrobe.get("accessories", [])
    acc_count = min(2, len(accessories_list))
    accessories = random.sample(accessories_list, k=acc_count) if acc_count > 0 else []
    outfit.update(
        {
            "top": top,
            "bottom": bottom,
            "dress": dress,
            "outer": outer,
            "shoes": shoes,
            "accessories": ", ".join([a["name"] for a in accessories]) if accessories else "",
        }
    )
    return outfit


def style_message() -> str:
    """Return a cheeky, body‑positive styling message."""
    messages = [
        "Rise & shine, Christa! Ready to glow today?",
        "You radiate confidence! This look is yours to own.",
        "Dressed to impress and ready to conquer!",
        "Shine bright—your smile is the best accessory.",
        "Feel fabulous, fearless and feminine!",
    ]
    return random.choice(messages)


def load_history() -> List[Dict[str, str]]:
    """Load rating history from the CSV file.  Returns a list of dicts."""
    history: List[Dict[str, str]] = []
    if RATING_FILE.exists():
        with open(RATING_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            history.extend(reader)
    return history


def save_rating(outfit: Dict[str, str], rating: int) -> None:
    """Append a new rating entry to the CSV file."""
    # Ensure file exists with header
    file_exists = RATING_FILE.exists()
    with open(RATING_FILE, "a", newline="", encoding="utf-8") as f:
        fieldnames = ["timestamp", "rating", "activity", "outfit"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "rating": str(rating),
                "activity": outfit.get("activity", ""),
                "outfit": json.dumps(outfit),
            }
        )


def generate_packing_list(days: int, destination: str, activity: str) -> Dict[str, List[str]]:
    """Produce a packing list for a multi‑day trip.

    For each day, a unique outfit is generated using the same logic as the daily
    outfit generator.  Items are aggregated to minimise over‑packing.  The
    function returns a dictionary with two keys: 'list' containing the unique
    items to pack and 'itineraries' mapping each day to its outfit.
    """
    # Determine destination coordinates; for this demo we only support Columbus.
    # In a full version you could integrate a geocoder here.
    coords = {
        "columbus": (39.9612, -82.9988),
        "cleveland": (41.4993, -81.6944),
    }
    dest_key = destination.strip().lower()
    lat, lon = coords.get(dest_key, (39.9612, -82.9988))
    packing_set = set()
    itineraries: Dict[str, Dict[str, str]] = {}
    # Track previously generated outfits to avoid repeats
    generated: List[Dict[str, str]] = []
    for day in range(1, days + 1):
        weather = get_weather(lat, lon)
        # Ensure we don't repeat the same outfit
        for _ in range(10):  # limit attempts
            outfit = choose_items(activity, weather)
            # Basic uniqueness check
            if outfit not in generated:
                generated.append(outfit)
                break
        itinerary_key = f"Day {day}"
        itineraries[itinerary_key] = outfit
        # Add items to packing set
        for key, value in outfit.items():
            if value:
                # split accessories
                if key == "accessories":
                    for item in value.split(","):
                        packing_set.add(item.strip())
                else:
                    packing_set.add(value)
    return {"list": sorted(packing_set), "itineraries": itineraries}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """Render the home page with links to all features."""
    history_count = len(load_history())
    settings = load_settings()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "history_count": history_count,
            "settings": settings,
        },
    )


@app.get("/outfit", response_class=HTMLResponse)
async def outfit_view(request: Request, activity: str = "Casual", reroll: int = 0) -> HTMLResponse:
    """Generate an outfit based on the selected activity and display it."""
    weather = get_weather()
    outfit = choose_items(activity, weather)
    message = style_message()
    # Embed activity into outfit dict for later storage
    outfit_with_activity = outfit.copy()
    outfit_with_activity["activity"] = activity
    # Pre‑serialise outfit for embedding as hidden form field.  Double quotes are
    # escaped to ensure valid HTML.
    import base64
    # Encode the outfit dict as URL‑safe base64 to safely embed in HTML without quoting issues
    outfit_json_str = json.dumps(outfit_with_activity)
    outfit_json_b64 = base64.urlsafe_b64encode(outfit_json_str.encode()).decode()
    return templates.TemplateResponse(
        "outfit.html",
        {
            "request": request,
            "outfit": outfit_with_activity,
            "weather": weather,
            "activity": activity,
            "message": message,
            "outfit_json_b64": outfit_json_b64,
        },
    )


@app.get("/rate")
async def rate_outfit_get(request: Request, rating: int, outfit_json: str) -> RedirectResponse:
    """Handle star rating submissions via query parameters and persist them.

    Using a GET route instead of POST avoids the need for the optional
    `python-multipart` dependency.  Ratings are appended to the CSV and the
    user is redirected to the history page.
    """
    import base64
    try:
        decoded = base64.urlsafe_b64decode(outfit_json + '==').decode()
        outfit = json.loads(decoded)
    except Exception:
        outfit = {"activity": "Unknown"}
    save_rating(outfit, int(rating))
    return RedirectResponse(url="/history", status_code=303)


@app.get("/history", response_class=HTMLResponse)
async def history_view(request: Request) -> HTMLResponse:
    """Display the user's rating history in reverse chronological order."""
    entries = load_history()
    # Sort entries by timestamp descending
    entries_sorted = sorted(entries, key=lambda x: x.get("timestamp", ""), reverse=True)
    # Parse outfits from JSON strings
    for entry in entries_sorted:
        try:
            outfit_dict = json.loads(entry.get("outfit", "{}"))
            entry["outfit_display"] = ", ".join(
                [
                    value
                    for key, value in outfit_dict.items()
                    if key in {"top", "bottom", "dress", "outer", "shoes", "accessories"}
                    and value
                ]
            )
        except Exception:
            entry["outfit_display"] = entry.get("outfit", "")
    return templates.TemplateResponse(
        "history.html", {"request": request, "entries": entries_sorted}
    )


@app.get("/packing", response_class=HTMLResponse)
async def packing_view(
    request: Request,
    days: Optional[int] = None,
    destination: Optional[str] = None,
    activity: Optional[str] = None,
) -> HTMLResponse:
    """Render the packing list form or results page."""
    if days and destination and activity:
        try:
            days_int = int(days)
        except ValueError:
            days_int = 1
        result = generate_packing_list(days_int, destination, activity)
        return templates.TemplateResponse(
            "packing.html",
            {
                "request": request,
                "days": days_int,
                "destination": destination,
                "activity": activity,
                "packing_list": result["list"],
                "itineraries": result["itineraries"],
            },
        )
    # Render blank form
    return templates.TemplateResponse(
        "packing.html",
        {
            "request": request,
            "days": None,
            "destination": None,
            "activity": None,
        },
    )


# =========================== New Feature Endpoints ===========================

@app.get("/wardrobe", response_class=HTMLResponse)
async def wardrobe_page(request: Request) -> HTMLResponse:
    """Display the current wardrobe and forms to add or remove items."""
    wardrobe = load_wardrobe()
    return templates.TemplateResponse(
        "wardrobe.html",
        {
            "request": request,
            "wardrobe": wardrobe,
        },
    )


@app.get("/wardrobe/add_item")
async def add_item(
    request: Request,
    category: str,
    name: str,
    warmth: Optional[str] = None,
    style: Optional[str] = None,
) -> RedirectResponse:
    """Add a new item to the wardrobe and persist it."""
    wardrobe = load_wardrobe()
    category_key = category.lower()
    item: Dict[str, str] = {"name": name.strip()}
    if warmth:
        item["warmth"] = warmth
    if style:
        item["style"] = style
    wardrobe.setdefault(category_key, []).append(item)
    save_json(WARDROBE_JSON, wardrobe)
    return RedirectResponse("/wardrobe", status_code=303)


@app.get("/wardrobe/delete_item")
async def delete_item(
    request: Request,
    category: str,
    name: str,
) -> RedirectResponse:
    """Remove an item from the wardrobe."""
    wardrobe = load_wardrobe()
    category_key = category.lower()
    items = wardrobe.get(category_key, [])
    wardrobe[category_key] = [i for i in items if i.get("name") != name]
    save_json(WARDROBE_JSON, wardrobe)
    return RedirectResponse("/wardrobe", status_code=303)


@app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request) -> HTMLResponse:
    """Display upcoming events and a form to add new events."""
    events = load_events()
    # Sort events by date/time
    def sort_key(item):
        data = item[1]
        return data.get("date", "9999-12-31"), data.get("time", "23:59")
    sorted_events = sorted(events.items(), key=sort_key)
    return templates.TemplateResponse(
        "calendar.html",
        {
            "request": request,
            "events": sorted_events,
        },
    )


@app.get("/calendar/add_event")
async def add_event(
    request: Request,
    name: str,
    date: str,
    time: str,
    style: str,
) -> RedirectResponse:
    """Add a new calendar event."""
    events = load_events()
    event_id = str(int(datetime.now().timestamp() * 1000))
    events[event_id] = {
        "name": name.strip(),
        "date": date,
        "time": time,
        "style": style,
    }
    save_json(EVENTS_JSON, events)
    return RedirectResponse("/calendar", status_code=303)


@app.get("/calendar/delete_event")
async def delete_event(
    request: Request,
    event_id: str,
) -> RedirectResponse:
    """Remove an event from the calendar."""
    events = load_events()
    events.pop(event_id, None)
    save_json(EVENTS_JSON, events)
    return RedirectResponse("/calendar", status_code=303)


@app.get("/events_outfits", response_class=HTMLResponse)
async def events_outfits(request: Request) -> HTMLResponse:
    """Generate outfit suggestions for upcoming events based on their style tags."""
    events = load_events()
    outfits: Dict[str, Dict[str, str]] = {}
    for event_id, info in events.items():
        style = info.get("style", "Casual")
        outfit = choose_items(style, {"temperature": 70.0, "precip": 0.0})
        outfit["activity"] = style
        outfits[event_id] = outfit
    return templates.TemplateResponse(
        "events_outfits.html",
        {
            "request": request,
            "events": events,
            "outfits": outfits,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> HTMLResponse:
    """Display user settings such as notification time."""
    settings = load_settings()
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings,
        },
    )


@app.get("/settings/update")
async def update_settings(
    request: Request,
    notification_time: str,
) -> RedirectResponse:
    """Update notification time setting."""
    settings = load_settings()
    if len(notification_time) == 5 and notification_time[2] == ":":
        settings["notification_time"] = notification_time
        save_settings(settings)
    return RedirectResponse("/settings", status_code=303)
