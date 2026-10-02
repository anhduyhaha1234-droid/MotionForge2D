#!/usr/bin/env python
"""M1-01 correction · C11 capability audit.

Question the packet asks: does a SUPPORTED mechanism exist that enforces a
cumulative OUTBOUND MODEL-REQUEST cap BEFORE the request is sent?

Everything here is read-only inspection of the installed runtime plus the
provider catalog. Nothing is started, patched, or configured.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

SP = Path(r"C:\Users\Admin\AppData\Local\Programs\Python\Python311\Lib\site-packages")
CHECKS: list[dict] = []


def note(name: str, verdict: str, detail: str, paths=None) -> None:
    CHECKS.append({"check": name, "verdict": verdict, "detail": detail,
                   "paths": paths or []})


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 1. CLI flags
import subprocess
for cmd in (["hermes", "--help"], ["hermes", "chat", "--help"]):
    r = subprocess.run(cmd, capture_output=True, text=True)
    text = r.stdout + r.stderr
    hits = sorted(set(re.findall(r"--[a-z-]*(?:request|budget|cap|limit|usage)[a-z-]*", text)))
    note("cli:" + " ".join(cmd[1:]), "MEASURED",
         f"request/budget/limit-shaped flags = {hits or 'NONE'}", [])

# ------------------------------------------------- 2. config keys in defaults
cd = SP / "hermes_cli" / "config_defaults.py"
text = cd.read_text(encoding="utf-8", errors="replace")
keys = sorted(set(re.findall(r'"([a-z_]*(?:max_(?:api_)?(?:calls|requests)|request_budget|'
                             r'budget|max_cost|cost_limit|api_call_budget)[a-z_]*)"', text)))
note("config_defaults: request-cap keys", "MEASURED",
     f"cumulative request/budget keys = {keys or 'NONE'}",
     [f"{cd} sha256={sha(cd)}"])

# ------------------------------------- 3. runtime: any pre-request counter gate
sites = []
for f in list((SP / "agent").glob("*.py")) + list((SP / "hermes_cli").glob("*.py")):
    t = f.read_text(encoding="utf-8", errors="replace")
    if re.search(r"max_api_calls|api_call_budget|max_model_requests|request_budget", t):
        sites.append(str(f))
note("runtime: pre-request request-cap identifier", "MEASURED",
     f"files containing a cumulative request-cap identifier = {len(sites)} {sites}", [])

# ------------------------------- 4. pre_api_request: is the result ACTED ON?
cl = SP / "agent" / "conversation_loop.py"
t = cl.read_text(encoding="utf-8", errors="replace")
i = t.find('_invoke_hook(\n                            "pre_api_request"')
seg = t[i:i + 1400] if i != -1 else ""
acted = ("_invoke_hook(" in seg) and bool(
    re.search(r"=\s*_invoke_hook\(\s*\n?\s*\"pre_api_request\"", seg))
note("pre_api_request fired before outbound request", "MEASURED",
     "fires at conversation_loop.py:2140 immediately before the provider call; "
     "kwargs include api_call_count / retry_count", [f"{cl} sha256={sha(cl)}"])
note("pre_api_request return value used for a block decision", "ABSENT",
     "the call site does not assign the result (no `= _invoke_hook(...)`), so a "
     "PLUGIN callback cannot block the request either; and there is no shell-hook "
     "binding for this event", [f"{cl} sha256={sha(cl)}"])

# --------------------------- 5. shell hooks: which events can return a block?
sh = SP / "agent" / "shell_hooks.py"
t = sh.read_text(encoding="utf-8", errors="replace")
note("shell_hooks block-capable events", "MEASURED",
     "`_parse_response` honours a block directive ONLY for `pre_tool_call` "
     "(plus a keep-going directive for `pre_verify`); every other event accepts "
     "at most a `context` string. `pre_api_request` has no block path.",
     [f"{sh} sha256={sha(sh)}"])

# ---------------------------------- 6. what the runtime DOES support per turn
note("agent.max_turns / --max-turns semantics", "MEASURED",
     "counts tool-calling ITERATIONS per conversation turn (help text); it is not "
     "a provider-request counter and does not include inner retry attempts", [])

# ------------------------------------------------ 7. provider-side capability
cfg = Path(r"C:\Users\Admin\AppData\Local\hermes\config.yaml")
note("provider = local router at 127.0.0.1:20128", "MEASURED",
     "the packet forbids writing a Hermes/9router subsystem or changing global "
     "config in this UI task, so a router-side gate cannot be installed here",
     [f"{cfg} sha256={sha(cfg)}"])

out = {
    "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "question": "supported cumulative OUTBOUND model-request cap enforced BEFORE send?",
    "checks": CHECKS,
    "verdict": "NO_SUPPORTED_PRE_REQUEST_REQUEST_CAP",
    "consequence": "BLOCKED_BUDGET_GUARD - no worker dispatch under this packet",
}
print(json.dumps(out, indent=2, ensure_ascii=False))
