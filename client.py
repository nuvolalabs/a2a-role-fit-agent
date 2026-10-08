#!/usr/bin/env python3
"""Minimal A2A v1.0 client: discover the Agent Card, then send a message.

Deliberately stdlib-only so the wire format is visible end to end:

  1. GET /.well-known/agent-card.json   -> pick an interface
  2. POST <interface url> (JSON-RPC 2.0) -> SendMessage
  3. Read the returned Task + artifacts

Usage:
    python client.py --url http://127.0.0.1:8024 "evaluate: <job description>"
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

A2A_VERSION = "1.0"


def get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "A2A-Version": A2A_VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json",
                 "A2A-Version": A2A_VERSION})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_agent_card(base_url: str) -> dict:
    """Step 1 of A2A: fetch the advertised Agent Card."""
    card = get_json(base_url.rstrip("/") + "/.well-known/agent-card.json")
    print("Agent Card")
    print("  name       :", card.get("name"))
    print("  version    :", card.get("version"))
    print("  description:", (card.get("description") or "")[:90])
    for iface in card.get("supportedInterfaces", []):
        print(f"  interface  : {iface.get('protocolBinding')} "
              f"v{iface.get('protocolVersion')} -> {iface.get('url')}")
    for skill in card.get("skills", []):
        print(f"  skill      : {skill['id']} - {skill['name']}")
    return card


def pick_jsonrpc_url(card: dict) -> str:
    """Choose the JSON-RPC interface from the card."""
    for iface in card.get("supportedInterfaces", []):
        if iface.get("protocolBinding") == "JSONRPC":
            return iface["url"]
    raise SystemExit("Agent Card advertises no JSONRPC interface")


def send_message(rpc_url: str, text: str, rpc_id: int = 1) -> dict:
    """Step 2 of A2A: SendMessage over JSON-RPC 2.0."""
    payload = {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": f"client-{rpc_id}",
                "role": "ROLE_USER",
                "parts": [{"text": text}],
            }
        },
    }
    return post_json(rpc_url, payload)


def artifact_text(task: dict) -> str:
    chunks = []
    for artifact in task.get("artifacts", []):
        for part in artifact.get("parts", []):
            if "text" in part:
                chunks.append(part["text"])
    return "\n".join(chunks)


def main() -> int:
    ap = argparse.ArgumentParser(description="A2A v1.0 client")
    ap.add_argument("text", help="text to send, e.g. a job description")
    ap.add_argument("--url", default="http://127.0.0.1:8024",
                    help="agent base URL (default: %(default)s)")
    ap.add_argument("--card-only", action="store_true",
                    help="just print the Agent Card and exit")
    args = ap.parse_args()

    card = fetch_agent_card(args.url)
    if args.card_only:
        return 0

    rpc_url = pick_jsonrpc_url(card)
    print(f"\n-> SendMessage to {rpc_url}")
    body = send_message(rpc_url, args.text)

    if "error" in body:
        print("JSON-RPC error:", json.dumps(body["error"], indent=2))
        return 1

    task = body["result"].get("task") or body["result"]
    print(f"task {task['id']}  state={task['status']['state']}")
    report = artifact_text(task)
    print("\n--- artifact ---")
    print(report or "(no artifact)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as exc:
        print(f"connection failed: {exc}", file=sys.stderr)
        sys.exit(2)
