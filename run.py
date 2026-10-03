"""Does routing by self-reported difficulty beat always-using-the-big-model?

Three arms over the same 14 objectively-graded tasks:
  cheap_only   - Qwen/Qwen3.8-27B for everything
  strong_only  - Qwen-Ambassador/Qwen3.8-Max for everything
  routed       - 27B first, escalate to Max when the 27B is unsure of itself

The question is not "which model is better" (the Max is). It is whether a cheap
escalation rule reaches Max-level accuracy for meaningfully fewer tokens.
"""
from __future__ import annotations

import json
import pathlib
import re
import statistics
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
from qwen_client import chat  # noqa: E402

CHEAP = "Qwen/Qwen3.8-27B"
STRONG = "Qwen-Ambassador/Qwen3.8-Max"
CONFIDENCE_THRESHOLD = 70

SYSTEM = (
    "Answer the question. Then end your reply with two final lines of exactly "
    "the form:\nANSWER: <value>\nCONFIDENCE: <integer 0-100>\n"
    "CONFIDENCE is how sure you are the ANSWER is correct. Be honest: a low "
    "number is useful, a flattering number is not."
)

TASKS = [
    # tier, prompt, expected
    ("easy", "What is 17 * 23?", "391"),
    ("easy", "What is 2 to the power of 10?", "1024"),
    ("easy", "How many minutes are in 3.5 hours?", "210"),
    ("easy", "Reverse the string 'ambassador'.", "rodassabma"),
    ("easy", "What is the 7th prime number (counting 2 as the 1st)?", "17"),
    ("easy", "How many letters are in the word 'qwen'?", "4"),
    ("medium", "A train travels 60 mph for 45 minutes, then 30 mph for 30 minutes. "
               "How many miles in total?", "60"),
    ("medium", "If 3 machines take 3 minutes to make 3 widgets, how many minutes do "
               "100 machines take to make 100 widgets?", "3"),
    ("medium", "What is 15% of 240, then add 12?", "48"),
    ("medium", "How many times does the letter 's' appear in 'mississippi'?", "4"),
    ("hard", "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than "
             "the ball. How much does the ball cost, in dollars?", "0.05"),
    ("hard", "If 5 machines take 5 minutes to make 5 devices, how many minutes do "
             "100 machines take to make 100 devices?", "5"),
    ("hard", "What is the next number in the sequence 2, 6, 12, 20, 30, ?", "42"),
    ("hard", "A patch of lily pads doubles in size every day and covers the whole "
             "lake in 48 days. How many days to cover half the lake?", "47"),
]

_ANSWER_RE = re.compile(r"ANSWER:\s*(.+)", re.IGNORECASE)
_CONF_RE = re.compile(r"CONFIDENCE:\s*(\d{1,3})", re.IGNORECASE)


def _norm(v: str) -> str:
    v = v.strip().strip("`*_ ").rstrip(".").replace(",", "").replace("$", "")
    if re.fullmatch(r"-?\d+\.0+", v):
        v = v.split(".")[0]
    if v.endswith(" minutes"):
        v = v[: -len(" minutes")]
    return v.lower()


def grade(text: str, expected: str) -> tuple[bool, str]:
    m = _ANSWER_RE.findall(text or "")
    if not m:
        return False, ""
    got = _norm(m[-1])
    return got == _norm(expected), got


def confidence(text: str) -> int | None:
    m = _CONF_RE.findall(text or "")
    if not m:
        return None
    return max(0, min(100, int(m[-1])))


def call(model: str, prompt: str) -> dict:
    res = chat(prompt, system=SYSTEM, model=model, max_tokens=1500, effort="low")
    return {
        "model": model,
        "ok": res["ok"],
        "http_status": res["http_status"],
        "content": res["content"],
        "confidence": confidence(res["content"]),
        "completion_tokens": res["usage"].get("completion_tokens") or 0,
        "prompt_tokens": res["usage"].get("prompt_tokens") or 0,
        "latency_s": res["latency_s"],
        "error": res["error"],
    }


def main() -> int:
    records = []
    for tier, prompt, expected in TASKS:
        cheap = call(CHEAP, prompt)
        cheap_ok, cheap_got = grade(cheap["content"], expected)

        strong = call(STRONG, prompt)
        strong_ok, strong_got = grade(strong["content"], expected)

        # routed: escalate when the cheap model is unsure or unparseable
        conf = cheap["confidence"]
        escalate = (not cheap_ok and conf is None) or (conf is not None and conf < CONFIDENCE_THRESHOLD)
        if escalate:
            routed_ok, routed_got = strong_ok, strong_got
            routed_model, routed_tokens, routed_latency = STRONG, strong["completion_tokens"], strong["latency_s"]
        else:
            routed_ok, routed_got = cheap_ok, cheap_got
            routed_model, routed_tokens, routed_latency = CHEAP, cheap["completion_tokens"], cheap["latency_s"]

        rec = {
            "tier": tier, "prompt": prompt, "expected": expected,
            "cheap_ok": cheap_ok, "cheap_got": cheap_got, "cheap_conf": conf,
            "cheap_tokens": cheap["completion_tokens"], "cheap_latency": cheap["latency_s"],
            "strong_ok": strong_ok, "strong_got": strong_got,
            "strong_tokens": strong["completion_tokens"], "strong_latency": strong["latency_s"],
            "escalated": escalate, "routed_ok": routed_ok, "routed_got": routed_got,
            "routed_model": routed_model, "routed_tokens": routed_tokens,
            "routed_latency": routed_latency,
        }
        records.append(rec)
        print(f"{tier:<6} cheap={'P' if cheap_ok else 'F'} conf={str(conf):>4} "
              f"strong={'P' if strong_ok else 'F'} -> {'ESCALATE' if escalate else 'keep  '} "
              f"routed={'P' if routed_ok else 'F'}")

    out = HERE / "results"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "raw.jsonl").open("w") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True) + "\n")

    def arm(name, ok_key, tok_key, lat_key):
        ok = sum(1 for r in records if r[ok_key])
        toks = sum(r[tok_key] for r in records)
        lat = statistics.fmean(r[lat_key] for r in records)
        return {
            "accuracy": round(ok / len(records), 3),
            "correct": ok,
            "total_completion_tokens": toks,
            "correct_per_1k_tokens": round((ok / toks) * 1000, 3) if toks else None,
            "mean_latency_s": round(lat, 2),
        }

    summary = {
        "tasks": len(records),
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "cheap_only": arm("cheap", "cheap_ok", "cheap_tokens", "cheap_latency"),
        "strong_only": arm("strong", "strong_ok", "strong_tokens", "strong_latency"),
        "routed": arm("routed", "routed_ok", "routed_tokens", "routed_latency"),
        "escalation_rate": round(sum(r["escalated"] for r in records) / len(records), 3),
        "escalations": [r["prompt"][:50] for r in records if r["escalated"]],
        "by_tier": {
            tier: {
                "cheap_correct": sum(1 for r in records if r["tier"] == tier and r["cheap_ok"]),
                "strong_correct": sum(1 for r in records if r["tier"] == tier and r["strong_ok"]),
                "routed_correct": sum(1 for r in records if r["tier"] == tier and r["routed_ok"]),
                "n": sum(1 for r in records if r["tier"] == tier),
            }
            for tier in ("easy", "medium", "hard")
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("\n=== summary ===")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
