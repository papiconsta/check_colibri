"""Run 30 eval cases against the tools in eval_20_tools.py and write an Excel report.

    uv run python -m check_colibri.evals.run_evals [--out results.xlsx]

Each case has: prompt(s), the tools the model is expected to call, and a check on the
final answer. Deterministic expected values are computed here with plain Python, so the
checks don't depend on the model's own arithmetic.
"""

import argparse
import base64
import hashlib
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from check_colibri.evals import eval_20_tools as T


# --- Helpers -----------------------------------------------------------------

def norm(s: str) -> str:
    """Lowercase and drop thousands separators / markdown noise for lenient matching."""
    return s.lower().replace(",", "").replace("*", "").replace("`", "")


def has(answer: str, *needles: str) -> bool:
    a = norm(answer)
    return all(norm(str(n)) in a for n in needles)


def any_of(answer: str, *needles: str) -> bool:
    a = norm(answer)
    return any(norm(n) in a for n in needles)


def call_args(calls: list[dict], name: str) -> list[dict]:
    return [c["args"] for c in calls if c["name"] == name]


def result_of(calls: list[dict], name: str) -> str:
    for c in calls:
        if c["name"] == name:
            return c["result"]
    return ""


def digest(text: str, algo: str) -> str:
    return hashlib.new(algo, text.encode()).hexdigest()


# Expected values
D1, D2 = "2026-01-01", "2026-11-13"
DAYS = (date.fromisoformat(D2) - date.fromisoformat(D1)).days
D_ADD = date(2026, 12, 20) + timedelta(days=15)
D_SUB = date(2026, 3, 1) - timedelta(days=1)
STATS_TEXT = "The quick brown fox. It jumps over the lazy dog!"
B64_TEXT = "Γεια σου Colibri"
B64_ENC = base64.b64encode(B64_TEXT.encode()).decode()


# --- Cases -------------------------------------------------------------------
# prompts: list of user turns (multi-turn cases share history and tool state).
# tools:   tool names that must be called ([] = no tool should be called).
# check:   (final_answer, calls) -> bool

CASES = [
    # Time & dates
    dict(id=1, cat="time", prompts=["What time is it right now in Europe/Athens?"],
         tools=["get_time"],
         check=lambda a, c: any(x.get("timezone") == "Europe/Athens" for x in call_args(c, "get_time"))),
    dict(id=2, cat="dates", prompts=[f"How many days are there between {D1} and {D2}?"],
         tools=["date_diff"], check=lambda a, c: has(a, DAYS)),
    dict(id=3, cat="dates", prompts=["What date is 15 days after 2026-12-20, and which weekday is it?"],
         tools=["add_days"], check=lambda a, c: has(a, D_ADD.isoformat(), D_ADD.strftime("%A"))),
    dict(id=4, cat="dates", prompts=["What was the date the day before 2026-03-01, and what weekday?"],
         tools=["add_days"], check=lambda a, c: has(a, D_SUB.isoformat(), D_SUB.strftime("%A"))),

    # Math & conversion
    dict(id=5, cat="math", prompts=["Calculate (12.5 * 4) / 3."],
         tools=["calculator"], check=lambda a, c: any_of(a, "16.67", "16.666")),
    dict(id=6, cat="math", prompts=["What is 2 ** 10 + 7?"],
         tools=["calculator"], check=lambda a, c: has(a, 1031)),
    dict(id=7, cat="chain", prompts=["Look up order A1001 and tell me its total converted to USD."],
         tools=["lookup_order", "convert_currency"],
         check=lambda a, c: any_of(a, "65.11", "65.1")),
    dict(id=8, cat="units", prompts=["Convert 5 km to miles."],
         tools=["convert_units"], check=lambda a, c: has(a, "3.10")),
    dict(id=9, cat="units", prompts=["How much is 100 degrees Fahrenheit in Celsius?"],
         tools=["convert_units"], check=lambda a, c: has(a, "37.7")),
    dict(id=10, cat="units", prompts=["Convert 70 kg to pounds."],
         tools=["convert_units"], check=lambda a, c: has(a, "154.3")),
    dict(id=11, cat="currency", prompts=["Convert 250 USD to EUR."],
         tools=["convert_currency"], check=lambda a, c: has(a, "230")),
    dict(id=12, cat="currency", prompts=["How many GBP is 10000 JPY?"],
         tools=["convert_currency"], check=lambda a, c: has(a, "52.14")),

    # Randomness & identifiers (answer must contain what the tool returned)
    dict(id=13, cat="random", prompts=["Roll a die: give me a random number between 1 and 6."],
         tools=["random_number"],
         check=lambda a, c: result_of(c, "random_number") != "" and has(a, result_of(c, "random_number"))),
    dict(id=14, cat="random", prompts=["Generate a new UUID for me."],
         tools=["generate_uuid"], check=lambda a, c: has(a, result_of(c, "generate_uuid"))),
    dict(id=15, cat="random", prompts=["Generate a 20 character password with no symbols."],
         tools=["generate_password"],
         check=lambda a, c: any(x.get("length") == 20 and x.get("symbols") is False
                                for x in call_args(c, "generate_password"))
         and has(a, result_of(c, "generate_password"))),

    # Text
    dict(id=16, cat="text", prompts=["What is the sha256 hash of the text 'colibri'?"],
         tools=["hash_text"], check=lambda a, c: has(a, digest("colibri", "sha256"))),
    dict(id=17, cat="text", prompts=["Give me the md5 of 'hello'."],
         tools=["hash_text"], check=lambda a, c: has(a, digest("hello", "md5"))),
    dict(id=18, cat="text", prompts=[f"Base64-encode this text: {B64_TEXT}"],
         tools=["base64_tool"], check=lambda a, c: has(a, B64_ENC)),
    dict(id=19, cat="text", prompts=["Decode this base64: SGVsbG8gQ29saWJyaQ=="],
         tools=["base64_tool"], check=lambda a, c: has(a, "Hello Colibri")),
    dict(id=20, cat="text", prompts=[f"Count the words and sentences in: \"{STATS_TEXT}\""],
         tools=["text_stats"], check=lambda a, c: has(a, len(STATS_TEXT.split())) and has(a, 2)),
    dict(id=21, cat="text", prompts=["Turn 'Hello World From Colibri!' into a URL slug."],
         tools=["transform_text"], check=lambda a, c: has(a, "hello-world-from-colibri")),
    dict(id=22, cat="text", prompts=["Extract all the numbers from: 'Order 66 shipped 3 items on 2026-11-13'."],
         tools=["regex_extract"], check=lambda a, c: has(a, "66", "2026")),
    dict(id=23, cat="text", prompts=["Is this valid JSON? {\"a\": 1,}"],
         tools=["validate_json"], check=lambda a, c: any_of(a, "invalid", "not valid", "isn't valid", "not a valid")),

    # Mock data
    dict(id=24, cat="data", prompts=["Τι καιρό κάνει στα Χανιά αυτή τη στιγμή;"],
         tools=["get_weather"], check=lambda a, c: has(a, "21")),
    dict(id=25, cat="error", prompts=["What's the weather in Paris right now?"],
         tools=["get_weather"],
         check=lambda a, c: any_of(a, "no weather data", "don't have", "do not have", "not available",
                                   "unable", "couldn't", "could not", "cannot", "can't", "unavailable", "not found")),
    dict(id=26, cat="data", prompts=["What's the status of order A1002 and when does it arrive?"],
         tools=["lookup_order"], check=lambda a, c: has(a, "transit", "2026-11-15") or has(a, "in_transit", "15")),
    dict(id=27, cat="data", prompts=["Was order A1003 refunded?"],
         tools=["lookup_order"], check=lambda a, c: any_of(a, "refund issued", "refunded", "refund has been issued", "yes")),
    dict(id=28, cat="multi", prompts=["Compare the weather in Athens and London: which is warmer and by how many degrees?"],
         tools=["get_weather"],
         check=lambda a, c: has(a, "athens") and has(a, "10")
         and len(call_args(c, "get_weather")) >= 2),
    dict(id=29, cat="state", prompts=["Save a note titled 'groceries' with the content 'milk, eggs, bread'.",
                                      "What's in my groceries note?"],
         tools=["save_note", "get_note"], check=lambda a, c: has(a, "eggs")),

    # No tool needed
    dict(id=30, cat="no_tool", prompts=["What is the capital of France?"],
         tools=[], check=lambda a, c: has(a, "paris")),
]


# --- Runner ------------------------------------------------------------------

def extract_calls(messages: list[dict]) -> list[dict]:
    results = {m["tool_call_id"]: m["content"] for m in messages if m.get("role") == "tool"}
    calls = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            raw = tc["function"]["arguments"]
            try:
                args = json.loads(raw or "{}")
            except json.JSONDecodeError:
                args = {"_raw": raw}
            calls.append({"name": tc["function"]["name"], "args": args, "result": results.get(tc["id"], "")})
    return calls


def run_case(case: dict) -> dict:
    T.NOTES.clear()
    messages = [{"role": "system", "content": T.SYSTEM_PROMPT}]
    answer, error = "", ""
    start = time.perf_counter()
    try:
        for prompt in case["prompts"]:
            messages.append({"role": "user", "content": prompt})
            answer = T.run_agent(messages)
    except Exception as e:  # server down, bad response, ...
        error = f"{type(e).__name__}: {e}"
    elapsed = time.perf_counter() - start

    calls = extract_calls(messages)
    called = {c["name"] for c in calls}
    expected = set(case["tools"])
    tools_ok = called == expected if not expected else expected <= called
    try:
        answer_ok = bool(case["check"](answer, calls)) and not error
    except Exception:
        answer_ok = False

    return {
        "id": case["id"], "category": case["cat"], "prompt": " ⏎ ".join(case["prompts"]),
        "expected_tools": ", ".join(case["tools"]) or "(none)",
        "actual_tools": ", ".join(c["name"] for c in calls) or "(none)",
        "tool_args": "; ".join(json.dumps(c["args"], ensure_ascii=False) for c in calls),
        "tool_results": "; ".join(c["result"][:120] for c in calls),
        "tool_errors": sum(c["result"].startswith("Error:") for c in calls),
        "steps": sum(m.get("role") == "assistant" for m in messages),
        "tools_ok": tools_ok, "answer_ok": answer_ok, "passed": tools_ok and answer_ok,
        "seconds": round(elapsed, 1), "answer": answer, "error": error,
    }


# --- Excel -------------------------------------------------------------------

GREEN = PatternFill("solid", fgColor="C6EFCE")
RED = PatternFill("solid", fgColor="FFC7CE")
HEAD = PatternFill("solid", fgColor="1F3864")


def write_excel(rows: list[dict], path: Path) -> None:
    wb = Workbook()

    # Summary
    ws = wb.active
    ws.title = "Summary"
    n = len(rows)
    passed = sum(r["passed"] for r in rows)
    ws.append(["Model", T.MODEL])
    ws.append(["Run at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    ws.append(["Cases", n])
    ws.append(["Passed", passed])
    ws.append(["Pass rate", passed / n])
    ws.append(["Right tools", sum(r["tools_ok"] for r in rows) / n])
    ws.append(["Right answer", sum(r["answer_ok"] for r in rows) / n])
    ws.append(["Avg seconds / case", round(sum(r["seconds"] for r in rows) / n, 1)])
    for r in (5, 6, 7):
        ws.cell(r, 2).number_format = "0.0%"
    for r in range(1, 9):
        ws.cell(r, 1).font = Font(bold=True)

    ws.append([])
    ws.append(["Category", "Cases", "Passed", "Pass rate"])
    hdr = ws.max_row
    for c in range(1, 5):
        ws.cell(hdr, c).font = Font(bold=True, color="FFFFFF")
        ws.cell(hdr, c).fill = HEAD
    for cat in dict.fromkeys(r["category"] for r in rows):
        sub = [r for r in rows if r["category"] == cat]
        ws.append([cat, len(sub), sum(r["passed"] for r in sub), sum(r["passed"] for r in sub) / len(sub)])
        ws.cell(ws.max_row, 4).number_format = "0.0%"
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 22

    # Results
    wr = wb.create_sheet("Results")
    cols = ["id", "category", "prompt", "expected_tools", "actual_tools", "tool_args", "tool_results",
            "tool_errors", "steps", "tools_ok", "answer_ok", "passed", "seconds", "answer", "error"]
    wr.append(cols)
    for c in range(1, len(cols) + 1):
        cell = wr.cell(1, c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD
    for r in rows:
        wr.append([("PASS" if r[k] else "FAIL") if k in ("tools_ok", "answer_ok", "passed") else r[k] for k in cols])
        for k in ("tools_ok", "answer_ok", "passed"):
            cell = wr.cell(wr.max_row, cols.index(k) + 1)
            cell.fill = GREEN if cell.value == "PASS" else RED
    widths = {"id": 5, "category": 10, "prompt": 45, "expected_tools": 22, "actual_tools": 26, "tool_args": 40,
              "tool_results": 45, "tool_errors": 8, "steps": 7, "tools_ok": 9, "answer_ok": 10, "passed": 8,
              "seconds": 8, "answer": 60, "error": 25}
    for i, k in enumerate(cols, 1):
        wr.column_dimensions[get_column_letter(i)].width = widths[k]
    for row in wr.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    wr.freeze_panes = "C2"
    wr.auto_filter.ref = wr.dimensions

    wb.save(path)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=f"eval_results_{datetime.now():%Y%m%d_%H%M%S}.xlsx")
    p.add_argument("--only", type=int, nargs="*", help="run only these case ids")
    args = p.parse_args()

    cases = [c for c in CASES if not args.only or c["id"] in args.only]
    rows = []
    for case in cases:
        row = run_case(case)
        rows.append(row)
        print(f"[{'PASS' if row['passed'] else 'FAIL'}] #{row['id']:>2} {row['category']:<8} "
              f"tools={row['actual_tools']}  ({row['seconds']}s)")

    out = Path(args.out)
    write_excel(rows, out)
    print(f"\n{sum(r['passed'] for r in rows)}/{len(rows)} passed -> {out.resolve()}")


if __name__ == "__main__":
    main()
