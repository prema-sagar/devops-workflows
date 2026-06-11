import os
import json
import sys
import requests
import anthropic

# ── Read config from environment variables ──────────────────────────────────
PROVIDER  = os.environ.get("MODEL_PROVIDER", "bedrock")
GH_TOKEN  = os.environ["GH_TOKEN"]
REPO      = os.environ["REPO"]
PR_NUMBER = os.environ["PR_NUMBER"]
MAX_LINES = int(os.environ.get("MAX_DIFF_LINES", "1500"))

# Models
BEDROCK_MODEL = "anthropic.claude-sonnet-4-20250514-v1:0"
DIRECT_MODEL  = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """You are an expert code reviewer for an enterprise DevOps team.
Review the PR diff provided and respond ONLY with a valid JSON object.
No text before or after the JSON. No markdown fences around it.

JSON schema to follow exactly:
{
  "verdict": "APPROVE or REQUEST_CHANGES or CRITICAL",
  "summary": "one sentence summary of the overall change",
  "issues": [
    {
      "severity": "critical or major or minor or suggestion",
      "file": "path/to/file.py",
      "line": 42,
      "message": "clear description of the issue"
    }
  ],
  "positives": ["list of things done well"],
  "score": 75
}

Severity definitions:
- critical   : security vulnerabilities, SQL injection, hardcoded secrets, data loss bugs
- major      : logic errors, performance problems, broken functionality
- minor      : style issues, poor naming, missing comments
- suggestion : improvements, refactoring ideas

Verdict rules:
- Use CRITICAL         if any issue has severity = critical
- Use REQUEST_CHANGES  if issues exist but none are critical
- Use APPROVE          if no significant issues found"""


def get_pr_diff():
    """Fetch the PR diff from GitHub API."""
    url = f"https://api.github.com/repos/{REPO}/pulls/{PR_NUMBER}"
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github.v3.diff"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    lines = response.text.splitlines()
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        lines.append(f"\n... diff truncated at {MAX_LINES} lines ...")
    return "\n".join(lines)


def call_claude(diff):
    """Send the diff to Claude via Bedrock or direct Anthropic API."""
    user_message = f"Review this pull request diff:\n\n```diff\n{diff}\n```"

    if PROVIDER == "bedrock":
        client = anthropic.AnthropicBedrock()
        model  = BEDROCK_MODEL
    else:
        client = anthropic.Anthropic()
        model  = DIRECT_MODEL

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text


def post_comment(result):
    """Post the review as a comment on the GitHub PR."""
    issues_md = ""
    for issue in result.get("issues", []):
        severity = issue.get("severity", "minor")
        emoji = {
            "critical"  : "🔴",
            "major"     : "🟠",
            "minor"     : "🟡",
            "suggestion": "💡"
        }.get(severity, "ℹ️")
        file_ref = issue.get("file", "unknown")
        line_ref = issue.get("line", "?")
        message  = issue.get("message", "No detail")
        issues_md += f"| {emoji} `{severity}` | `{file_ref}:{line_ref}` | {message} |\n"

    positives_md = "\n".join(
        f"- ✅ {p}" for p in result.get("positives", [])
    )

    verdict_emoji = {
        "APPROVE"        : "✅",
        "REQUEST_CHANGES": "🔁",
        "CRITICAL"       : "🚨"
    }.get(result.get("verdict", ""), "🤔")

    score   = result.get("score", "N/A")
    verdict = result.get("verdict", "UNKNOWN")
    summary = result.get("summary", "")

    comment_body = f"""## 🤖 Claude AI Code Review
> **Score: {score}/100** &nbsp;·&nbsp; Powered by Amazon Bedrock (Claude 3.5 Sonnet v2)

### {verdict_emoji} Verdict: `{verdict}`

{summary}

---

### Issues Found

| Severity | Location | Detail |
|----------|----------|--------|
{issues_md if issues_md else "| — | — | No issues found 🎉 |"}

### What Was Done Well

{positives_md if positives_md else "— Nothing noted"}
"""

    url = f"https://api.github.com/repos/{REPO}/issues/{PR_NUMBER}/comments"
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    response = requests.post(url, headers=headers, json={"body": comment_body})
    response.raise_for_status()
    print("✅ Review comment posted to PR successfully")


if __name__ == "__main__":
    print("Step 1/4: Fetching PR diff from GitHub...")
    diff = get_pr_diff()
    print(f"Step 2/4: Diff fetched — {len(diff.splitlines())} lines")

    print("Step 3/4: Sending diff to Claude via Amazon Bedrock...")
    raw_response = call_claude(diff)

    print("Step 4/4: Parsing response and posting comment...")
    try:
        clean = raw_response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(clean)
    except json.JSONDecodeError as e:
        print(f"ERROR: Could not parse Claude response as JSON.", file=sys.stderr)
        print(f"Parse error: {e}", file=sys.stderr)
        print(f"Raw response was:\n{raw_response}", file=sys.stderr)
        sys.exit(1)

    post_comment(result)

    with open("review_result.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"✅ DONE — Verdict: {result.get('verdict')} | Score: {result.get('score')}/100")
