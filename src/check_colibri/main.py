import json
from datetime import datetime

from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="EMPTY")
MODEL = "qwen3.6-colibri"
MAX_STEPS = 10

SYSTEM_PROMPT = "You are a helpful assistant. Use the tools when they help."


# --- Tools -------------------------------------------------------------------
# Each tool is a plain function plus a JSON schema the model sees.

def get_time() -> str:
    return datetime.now().isoformat()


TOOL_FUNCTIONS = {
    "get_time": get_time,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get the current local date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


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
