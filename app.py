#!/usr/bin/env python3
"""Live Azure Pipelines dashboard.

A background thread polls the Azure DevOps Builds API every POLL_SECONDS and
caches the result. The page reads /api/state, so browser count never affects
API load. Run with ONE gunicorn worker (threads are fine) so only one poller exists.
"""
import logging
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template

ORG = os.environ["AZDO_ORG"]
PROJECTS = [p.strip() for p in os.environ["AZDO_PROJECTS"].split(",") if p.strip()]
PAT = os.environ["AZDO_PAT"]
POLL = int(os.environ.get("POLL_SECONDS", "30"))
HISTORY = int(os.environ.get("HISTORY_RUNS", "12"))
STAGE_POLL = int(os.environ.get("STAGE_POLL_SECONDS", "5"))  # running builds only
LOOKBACK = int(os.environ.get("LOOKBACK_BUILDS", "300"))  # builds fetched per project
API_VERSION = "7.1"
BASE = f"https://dev.azure.com/{ORG}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("azdo-dashboard")

session = requests.Session()
session.auth = ("", PAT)  # PAT goes in the password field, username blank
session.headers["Accept"] = "application/json"

state = {"pipelines": [], "updated": None, "error": None}
lock = threading.Lock()

STATE_ORDER = {"running": 0, "failed": 1, "queued": 2, "partial": 3,
               "canceled": 4, "passed": 5, "unknown": 6}

def iso(ts):
    """Azure returns 7 fractional digits; trim to 6 so every parser is happy."""
    return re.sub(r"(\.\d{6})\d+", r"\1", ts) if ts else None

def get(url, **params):
    params["api-version"] = API_VERSION
    r = session.get(url, params=params, timeout=20)
    # A bad/expired PAT gets a 203 with the HTML sign-in page, not a 401.
    if r.status_code in (203, 401):
        raise RuntimeError("Azure DevOps rejected the PAT. Check it hasn't expired "
                           "and has the Build (Read) scope.")
    r.raise_for_status()
    return r.json()

def classify(b):
    status, result = b.get("status"), b.get("result")
    if status in ("inProgress", "cancelling"):
        return "running"
    if status == "notStarted":
        return "queued"
    return {"succeeded": "passed", "partiallySucceeded": "partial",
            "failed": "failed", "canceled": "canceled"}.get(result, "unknown")

timeline_cache = {}  # build_id -> stages; only finished builds, since they never change

def record_state(r, waiting_ids):
    if r["id"] in waiting_ids:
        return "waiting"
    s = r.get("state")
    if s == "pending":
        return "pending"
    if s == "inProgress":
        return "running"
    return {"succeeded": "passed", "succeededWithIssues": "partial", "failed": "failed",
            "canceled": "canceled", "abandoned": "canceled",
            "skipped": "skipped"}.get(r.get("result"), "unknown")

def stages_for(project, build_id, finished):
    """Ordered stages (YAML) or jobs (classic / stageless YAML) for one run."""
    if finished and build_id in timeline_cache:
        return timeline_cache[build_id]
    try:
        records = get(f"{BASE}/{project}/_apis/build/builds/{build_id}/timeline").get("records") or []
    except Exception as e:  # stages are nice-to-have; never fail the poll over them
        log.warning("timeline for build %s failed: %s", build_id, e)
        return None
    # A stage with a live Checkpoint child is sitting at an approval/check gate
    waiting_ids = {r.get("parentId") for r in records
                   if r.get("type") == "Checkpoint" and r.get("state") == "inProgress"}
    stages = [r for r in records if r.get("type") == "Stage"]
    if not stages or all(r.get("name") == "__default" for r in stages):
        stages = [r for r in records if r.get("type") == "Job"]
    out = [{"name": r.get("name"), "state": record_state(r, waiting_ids),
            "started": iso(r.get("startTime")), "finished": iso(r.get("finishTime"))}
           for r in sorted(stages, key=lambda r: r.get("order") or 0)]
    if finished:
        timeline_cache[build_id] = out
    return out

def attach_stages(project, latest):
    live = latest["state"] in ("running", "queued")
    latest["stages"] = stages_for(project, latest["id"], finished=not live)
    running = [s["name"] for s in latest["stages"] or [] if s["state"] in ("running", "waiting")]
    latest["stage"] = running[0] if running else None

def summarize(b):
    return {
        "id": b["id"],
        "number": b.get("buildNumber"),
        "state": classify(b),
        "branch": (b.get("sourceBranch") or "").removeprefix("refs/heads/"),
        "who": (b.get("requestedFor") or {}).get("displayName"),
        "reason": b.get("reason"),
        "queued": iso(b.get("queueTime")),
        "started": iso(b.get("startTime")),
        "finished": iso(b.get("finishTime")),
        "url": (b.get("_links") or {}).get("web", {}).get("href"),
    }

def poll_once():
    pipelines = []
    for project in PROJECTS:
        builds = get(f"{BASE}/{project}/_apis/build/builds",
                     **{"$top": LOOKBACK, "queryOrder": "queueTimeDescending"})["value"]
        runs_by_def, defs = defaultdict(list), {}
        for b in builds:
            d = b["definition"]
            runs_by_def[d["id"]].append(b)
            defs[d["id"]] = d
        for def_id, runs in runs_by_def.items():
            runs = runs[:HISTORY]
            latest = summarize(runs[0])
            attach_stages(project, latest)
            pipelines.append({
                "project": project,
                "name": defs[def_id]["name"],
                "folder": (defs[def_id].get("path") or "\\").strip("\\"),
                "latest": latest,
                # oldest -> newest, excluding the latest run shown in the status cell
                "history": [{"state": classify(r), "number": r.get("buildNumber"),
                             "url": (r.get("_links") or {}).get("web", {}).get("href")}
                            for r in reversed(runs[1:])],
            })
    pipelines.sort(key=lambda p: p["latest"]["queued"] or "", reverse=True)  # newest first
    return pipelines

def poller():
    while True:
        try:
            data = poll_once()
            with lock:
                state.update(pipelines=data, error=None,
                             updated=datetime.now(timezone.utc).isoformat())
            log.info("polled %d pipelines across %d project(s)", len(data), len(PROJECTS))
        except Exception as e:
            log.error("poll failed: %s", e)
            with lock:
                state["error"] = str(e)  # keep last good data on screen
        time.sleep(POLL)

def stage_refresher():
    """Between full polls, refresh stages of running runs every STAGE_POLL seconds."""
    while True:
        time.sleep(STAGE_POLL)
        with lock:
            live = [(p["project"], p["latest"]) for p in state["pipelines"]
                    if p["latest"]["state"] in ("running", "queued")]
        for project, latest in live:
            fresh = dict(latest)
            attach_stages(project, fresh)
            with lock:
                latest.update(stages=fresh["stages"], stage=fresh["stage"])
        if live:
            timeline_cache_trim()

def timeline_cache_trim(limit=2000):
    while len(timeline_cache) > limit:
        timeline_cache.pop(next(iter(timeline_cache)))

app = Flask(__name__)
threading.Thread(target=poller, daemon=True, name="azdo-poller").start()
threading.Thread(target=stage_refresher, daemon=True, name="azdo-stages").start()

@app.route("/")
def index():
    return render_template("index.html", org=ORG, poll=POLL)

@app.route("/api/state")
def api_state():
    with lock:
        return jsonify(state)

@app.route("/healthz")
def healthz():
    with lock:
        return ({"ok": state["error"] is None, "updated": state["updated"]},
                200 if state["updated"] else 503)

if __name__ == "__main__":
    # No debug=True: the reloader would start a second poller thread.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5050")))
