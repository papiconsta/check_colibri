import ast
import base64
import hashlib
import json
import operator
import random
import re
import secrets
import string
import uuid
from datetime import date, datetime, timedelta

 
from openai import OpenAI
 
client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="EMPTY")
MODEL = "qwen3.6-colibri"
MAX_STEPS = 10
 
SYSTEM_PROMPT = "You are a helpful assistant. Use the tools when they help."
 
 
# --- Tool registry -----------------------------------------------------------
# @tool registers the function and builds its JSON schema in one place.
 
TOOL_FUNCTIONS: dict = {}
TOOLS: list[dict] = []
 
 
def tool(description: str, properties: dict | None = None, required: list[str] | None = None):
    def decorator(fn):
        TOOL_FUNCTIONS[fn.__name__] = fn
        TOOLS.append({
            "type": "function",
            "function": {
                "name": fn.__name__,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties or {},
                    "required": required or [],
                },
            },
        })
        return fn
    return decorator
 
 
def _parse_date(s: str) -> date:
    return date.fromisoformat(s)
 
 
# --- Time & dates ------------------------------------------------------------
 
@tool(
    "Get the current date and time. Optionally in a given IANA timezone (e.g. 'Europe/Athens').",
    {"timezone": {"type": "string", "description": "IANA timezone name. Omit for local time."}},
)
def get_time(timezone: str | None = None) -> str:
    if timezone:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(timezone)).isoformat()
    return datetime.now().isoformat()
 
 
@tool(
    "Number of days between two dates (end - start). Dates in YYYY-MM-DD.",
    {
        "start": {"type": "string", "description": "Start date, YYYY-MM-DD"},
        "end": {"type": "string", "description": "End date, YYYY-MM-DD"},
    },
    ["start", "end"],
)
def date_diff(start: str, end: str) -> str:
    return str((_parse_date(end) - _parse_date(start)).days)
 
 
@tool(
    "Add (or subtract, with a negative number) days to a date. Returns the new date and weekday.",
    {
        "date": {"type": "string", "description": "Date, YYYY-MM-DD"},
        "days": {"type": "integer", "description": "Days to add; negative to subtract"},
    },
    ["date", "days"],
)
def add_days(date: str, days: int) -> str:
    d = _parse_date(date) + timedelta(days=int(days))
    return json.dumps({"date": d.isoformat(), "weekday": d.strftime("%A")})
 
 
# --- Math & conversion -------------------------------------------------------
 
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
 
 
def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("unsupported expression")
 
 
@tool(
    "Evaluate an arithmetic expression. Supports + - * / // % ** and parentheses.",
    {"expression": {"type": "string", "description": "e.g. '(12.5 * 4) / 3'"}},
    ["expression"],
)
def calculator(expression: str) -> str:
    return str(_safe_eval(ast.parse(expression, mode="eval")))
 
 
_LENGTH = {"mm": 0.001, "cm": 0.01, "m": 1, "km": 1000, "in": 0.0254, "ft": 0.3048, "mi": 1609.344}
_MASS = {"g": 0.001, "kg": 1, "lb": 0.45359237, "oz": 0.028349523125}
 
 
@tool(
    "Convert between units. Length: mm, cm, m, km, in, ft, mi. Mass: g, kg, lb, oz. Temperature: C, F, K.",
    {
        "value": {"type": "number"},
        "from_unit": {"type": "string"},
        "to_unit": {"type": "string"},
    },
    ["value", "from_unit", "to_unit"],
)
def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    value = float(value)
    for table in (_LENGTH, _MASS):
        if from_unit in table and to_unit in table:
            return str(round(value * table[from_unit] / table[to_unit], 6))
    temps = {"C", "F", "K"}
    if from_unit in temps and to_unit in temps:
        c = {"C": value, "F": (value - 32) * 5 / 9, "K": value - 273.15}[from_unit]
        out = {"C": c, "F": c * 9 / 5 + 32, "K": c + 273.15}[to_unit]
        return str(round(out, 4))
    raise ValueError(f"cannot convert {from_unit} to {to_unit}")
 
 
_RATES_TO_EUR = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17, "CHF": 1.05, "JPY": 0.0061}
 
 
@tool(
    "Convert money between currencies using FIXED test rates (not live). Supports EUR, USD, GBP, CHF, JPY.",
    {
        "amount": {"type": "number"},
        "from_currency": {"type": "string", "description": "ISO code, e.g. USD"},
        "to_currency": {"type": "string", "description": "ISO code, e.g. EUR"},
    },
    ["amount", "from_currency", "to_currency"],
)
def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    f, t = from_currency.upper(), to_currency.upper()
    if f not in _RATES_TO_EUR or t not in _RATES_TO_EUR:
        raise ValueError(f"unsupported currency; use one of {list(_RATES_TO_EUR)}")
    return f"{round(float(amount) * _RATES_TO_EUR[f] / _RATES_TO_EUR[t], 2)} {t}"
 
 
# --- Randomness & identifiers -----------------------------------------------
 
@tool(
    "Return a random integer between min and max (inclusive).",
    {"min": {"type": "integer"}, "max": {"type": "integer"}},
    ["min", "max"],
)
def random_number(min: int, max: int) -> str:
    return str(random.randint(int(min), int(max)))
 
 
@tool("Generate a new random UUID v4.")
def generate_uuid() -> str:
    return str(uuid.uuid4())
 
 
@tool(
    "Generate a random password.",
    {
        "length": {"type": "integer", "description": "8-64, default 16"},
        "symbols": {"type": "boolean", "description": "Include symbols, default true"},
    },
)
def generate_password(length: int = 16, symbols: bool = True) -> str:
    length = int(length)
    if not 8 <= length <= 64:
        raise ValueError("length must be between 8 and 64")
    alphabet = string.ascii_letters + string.digits + ("!@#$%^&*-_" if symbols else "")
    return "".join(secrets.choice(alphabet) for _ in range(length))
 
 
# --- Text --------------------------------------------------------------------
 
@tool(
    "Hash text with md5, sha1, or sha256 and return the hex digest.",
    {
        "text": {"type": "string"},
        "algorithm": {"type": "string", "enum": ["md5", "sha1", "sha256"]},
    },
    ["text"],
)
def hash_text(text: str, algorithm: str = "sha256") -> str:
    if algorithm not in {"md5", "sha1", "sha256"}:
        raise ValueError("algorithm must be md5, sha1 or sha256")
    return hashlib.new(algorithm, text.encode()).hexdigest()
 
 
@tool(
    "Base64 encode or decode text.",
    {
        "text": {"type": "string"},
        "mode": {"type": "string", "enum": ["encode", "decode"]},
    },
    ["text", "mode"],
)
def base64_tool(text: str, mode: str) -> str:
    if mode == "encode":
        return base64.b64encode(text.encode()).decode()
    if mode == "decode":
        return base64.b64decode(text.encode()).decode()
    raise ValueError("mode must be 'encode' or 'decode'")
 
 
@tool(
    "Count characters, words, sentences and lines in a text.",
    {"text": {"type": "string"}},
    ["text"],
)
def text_stats(text: str) -> str:
    return json.dumps({
        "characters": len(text),
        "words": len(text.split()),
        "sentences": len([s for s in re.split(r"[.!?;]+", text) if s.strip()]),
        "lines": len(text.splitlines()) or 1,
    })
 
 
@tool(
    "Transform text: upper, lower, title, reverse, or slug (url-friendly).",
    {
        "text": {"type": "string"},
        "operation": {"type": "string", "enum": ["upper", "lower", "title", "reverse", "slug"]},
    },
    ["text", "operation"],
)
def transform_text(text: str, operation: str) -> str:
    ops = {
        "upper": str.upper,
        "lower": str.lower,
        "title": str.title,
        "reverse": lambda s: s[::-1],
        "slug": lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-"),
    }
    if operation not in ops:
        raise ValueError(f"operation must be one of {list(ops)}")
    return ops[operation](text)
 
 
@tool(
    "Find all matches of a regular expression in a text. Returns a JSON list.",
    {
        "text": {"type": "string"},
        "pattern": {"type": "string", "description": "Python regex, e.g. '\\\\d+'"},
    },
    ["text", "pattern"],
)
def regex_extract(text: str, pattern: str) -> str:
    return json.dumps(re.findall(pattern, text), ensure_ascii=False)
 
 
@tool(
    "Check whether a string is valid JSON. Returns 'valid' with the pretty-printed JSON, or the parse error.",
    {"text": {"type": "string"}},
    ["text"],
)
def validate_json(text: str) -> str:
    try:
        return "valid\n" + json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"invalid: {e}"
 
 
# --- Notes (in-memory state across turns) -----------------------------------
 
NOTES: dict[str, str] = {}
 
 
@tool(
    "Save a note under a title (overwrites if the title exists).",
    {"title": {"type": "string"}, "content": {"type": "string"}},
    ["title", "content"],
)
def save_note(title: str, content: str) -> str:
    NOTES[title] = content
    return f"saved note '{title}'"
 
 
@tool("List the titles of all saved notes.")
def list_notes() -> str:
    return json.dumps(list(NOTES)) if NOTES else "no notes saved"
 
 
@tool(
    "Read a saved note by its exact title.",
    {"title": {"type": "string"}},
    ["title"],
)
def get_note(title: str) -> str:
    if title not in NOTES:
        raise KeyError(f"no note titled '{title}'")
    return NOTES[title]
 
 
# --- Mock external data (deterministic, good for evals) ---------------------
 
_WEATHER = {
    "athens": {"temp_c": 19, "condition": "sunny", "humidity": 55},
    "chania": {"temp_c": 21, "condition": "partly cloudy", "humidity": 62},
    "thessaloniki": {"temp_c": 14, "condition": "rain", "humidity": 80},
    "london": {"temp_c": 9, "condition": "overcast", "humidity": 85},
}
 
 
@tool(
    "Get current weather for a city (MOCK data). Known: Athens, Chania, Thessaloniki, London.",
    {"city": {"type": "string"}},
    ["city"],
)
def get_weather(city: str) -> str:
    data = _WEATHER.get(city.strip().lower())
    if data is None:
        raise KeyError(f"no weather data for '{city}'")
    return json.dumps({"city": city, **data})
 
 
_ORDERS = {
    "A1001": {"status": "delivered", "items": ["headphones"], "total_eur": 59.90, "delivered_on": "2026-11-02"},
    "A1002": {"status": "in_transit", "items": ["keyboard", "mouse"], "total_eur": 89.00, "eta": "2026-11-15"},
    "A1003": {"status": "cancelled", "items": ["monitor"], "total_eur": 229.00, "refund": "issued"},
}
 
 
@tool(
    "Look up an order by ID in the shop database (MOCK). IDs look like 'A1001'.",
    {"order_id": {"type": "string"}},
    ["order_id"],
)
def lookup_order(order_id: str) -> str:
    order = _ORDERS.get(order_id.strip().upper())
    if order is None:
        raise KeyError(f"order '{order_id}' not found")
    return json.dumps({"order_id": order_id.upper(), **order})
 
 
def run_tool(name: str, arguments: str) -> str:
    """Execute a tool call; errors go back to the model as text so it can recover."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return f"Error: unknown tool '{name}'"
    try:
        args = json.loads(arguments or "{}")
        return str(fn(**args))
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"
 
 
# --- Agent loop --------------------------------------------------------------
 
def run_agent(messages: list[dict]) -> str:
    """Call the model repeatedly, executing tool calls, until it answers in text."""
    for _ in range(MAX_STEPS):
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            temperature=0.7,
        )
        msg = resp.choices[0].message
 
        # Keep the assistant turn (including its tool_calls) in the history.
        messages.append(msg.model_dump(exclude_none=True))
 
        if not msg.tool_calls:
            return msg.content or ""
 
        for call in msg.tool_calls:
            result = run_tool(call.function.name, call.function.arguments)
            print(f"  [tool] {call.function.name}({call.function.arguments}) -> {result}")
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )
 
    return "Stopped: reached the maximum number of steps."
 
 
def main() -> None:
    print(f"Loaded {len(TOOLS)} tools: {', '.join(TOOL_FUNCTIONS)}")
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_input in {"exit", "quit"}:
            break
        if not user_input:
            continue
 
        messages.append({"role": "user", "content": user_input})
        print(f"agent> {run_agent(messages)}")
 
 
if __name__ == "__main__":
    main()
 
