import os
import json
import sys

# ── Read config from environment variables ──────────────────────────────────
FAIL_ON_CRITICAL = os.environ.get("FAIL_ON_CRITICAL", "true").lower() == "true"
RESULT_FILE      = os.environ.get("REVIEW_RESULT_FILE", "review_result.json")
MIN_SCORE        = int(os.environ.get("MIN_SCORE", "40"))

# ── Read the review result written by claude_pr_review.py ───────────────────
try:
    with open(RESULT_FILE) as f:
        result = json.load(f)
except FileNotFoundError:
    print(f"ERROR: {RESULT_FILE} not found. Did the review step run successfully?",
          file=sys.stderr)
    sys.exit(1)

verdict   = result.get("verdict", "UNKNOWN")
score     = result.get("score", 100)
issues    = result.get("issues", [])
criticals = sum(1 for i in issues if i.get("severity") == "critical")

# ── Print summary ────────────────────────────────────────────────────────────
print("=" * 45)
print("           QUALITY GATE RESULT")
print("=" * 45)
print(f"  Verdict    : {verdict}")
print(f"  Score      : {score} / 100")
print(f"  Issues     : {len(issues)} total  ({criticals} critical)")
print("=" * 45)

# ── Evaluate gate conditions ─────────────────────────────────────────────────
if FAIL_ON_CRITICAL and verdict == "CRITICAL":
    print("❌  GATE FAILED — CRITICAL issues detected.")
    print("    Merge is blocked until critical issues are fixed.")
    sys.exit(1)

if score < MIN_SCORE:
    print(f"❌  GATE FAILED — Score {score} is below minimum {MIN_SCORE}.")
    sys.exit(1)

print("✅  GATE PASSED — Safe to merge.")
