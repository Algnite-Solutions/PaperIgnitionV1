#!/usr/bin/env python3
"""PaperIgnition OpenClaw skill — Feishu delivery helper.

All paper search and digest commands go through the `paperignition` CLI
directly (invoked from SKILL.md). This module only provides OpenClaw-specific
delivery channels that have no CLI equivalent.
"""

import json
import os
import sys
import urllib.error
import urllib.request


def _load_env():
    """Load .env from skill directory if env vars aren't already set."""
    env_keys = ["PI_API_KEY", "PI_BASE_URL", "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_OPEN_ID"]
    if all(os.environ.get(k) for k in env_keys):
        return
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key in env_keys and not os.environ.get(key):
                os.environ[key] = value


_load_env()

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_OPEN_ID = os.environ.get("FEISHU_OPEN_ID", "")


def _get_token() -> str:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = json.dumps({"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result["tenant_access_token"]
    except (urllib.error.URLError, KeyError) as e:
        print(f"Error getting Feishu token: {e}", file=sys.stderr)
        sys.exit(1)


def send_feishu(text: str) -> dict:
    if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_OPEN_ID]):
        print(
            "Error: FEISHU_APP_ID, FEISHU_APP_SECRET, and FEISHU_OPEN_ID env vars required",
            file=sys.stderr,
        )
        sys.exit(2)

    token = _get_token()
    url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
    content = json.dumps({"text": text})
    body = json.dumps({
        "receive_id": FEISHU_OPEN_ID,
        "msg_type": "text",
        "content": content,
    }).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        print(f"Error: Feishu HTTP {e.code} — {body_text}", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "feishu" or len(sys.argv) < 3:
        print('Usage: ./skill.py feishu "message text"', file=sys.stderr)
        sys.exit(1)

    message = " ".join(sys.argv[2:])
    result = send_feishu(message)
    if result.get("code") == 0:
        print("OK: message sent")
    else:
        print(f"ERROR: {result.get('code')} {result.get('msg')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
