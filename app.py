#!/usr/bin/env python3
"""Live Azure Pipelines dashboard.

A background thread polls the Azure DevOps Builds API and the classic Releases API
every POLL_SECONDS and caches the result. The page reads /api/state, so browser count never affects
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
LOOKBACK_REL = int(os.environ.get("LOOKBACK_RELEASES", "200"))  # releases fetched per project
RELEASES = os.environ.get("ENABLE_RELEASES", "true").lower() != "false"
API_VERSION = "7.1"
BASE = f"https://dev.azure.com/{ORG}"
VSRM = f"https://vsrm.dev.azure.com/{ORG}"  # classic Releases live on a separate host

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("azdo-dashboard")

session = requests.Session()
session.auth = ("", PAT)  # PAT goes in the password field, username blank
session.headers["Accept"] = "application/json"

state = {"pipelines": [], "releases": [], "updated": None, "error": None, "release_error": None}
lock = threading.Lock()

STATE_ORDER = {"running": 0, "failed": 1, "queued": 2, "partial": 3,
               "canceled": 4, "passed": 5, "unknown": 6}


def iso(ts):
    """Azure returns 7 fractional digits; trim to 6 so every parser is happy."""
    return re.sub(r"(\.\d{6})\d+", r"\1", ts) if ts else None


def request(url, params):
    params["api-version"] = API_VERSION
    r = session.get(url, params=params, timeout=30)
    # A bad/expired PAT gets a 203 with the HTML sign-in page, not a 401.
    if r.status_code in (203, 401):
        raise RuntimeError("Azure DevOps rejected the PAT. Check it hasn't expired "
                           "and has the Build (Read) and Release (Read) scopes.")
    r.raise_for_status()
    return r


def get(url, **params):
    return request(url, params).json()


def get_paged(url, limit, **params):
    """List endpoints return at most 100 items per call and a continuation token for the rest."""
    out, token = [], None
    while len(out) < limit:
        page = dict(params, **{"$top": min(100, limit - len(out))})
        if token:
            page["continuationToken"] = token
        r = request(url, page)
        out += r.json().get("value", [])
        token = r.headers.get("x-ms-continuationtoken")
        if not token:
            break
    return out


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


# ---------------------------------------------------------------- classic releases

DONE = {"passed", "partial", "failed", "canceled"}
ACTIVE = {"running", "waiting", "queued"}
ENV_STATE = {"succeeded": "passed", "partiallySucceeded": "partial", "rejected": "failed",
             "canceled": "canceled", "inProgress": "running", "queued": "queued",
             "scheduled": "pending", "notStarted": "pending"}


def env_waiting(e):
    """A manual pre- or post-deployment approval that nobody has actioned yet."""
    for key in ("preDeployApprovals", "postDeployApprovals"):
        for a in e.get(key) or []:
            if a.get("status") == "pending" and not a.get("isAutomated"):
                return True
    return False


def parse_env(e):
    state = "waiting" if env_waiting(e) else ENV_STATE.get(e.get("status"), "unknown")
    started = finished = None
    steps = e.get("deploySteps") or []  # only present on the full release, not the list
    if steps:
        last = steps[-1]
        phases = [ph["startedOn"] for ph in last.get("releaseDeployPhases") or [] if ph.get("startedOn")]
        started = min(phases) if phases else last.get("queuedOn")
        if state in DONE:
            finished = last.get("lastModifiedOn")
    elif state in DONE:
        finished = e.get("modifiedOn")
    minutes = e.get("timeToDeploy") or 0
    return {"name": e.get("name"), "state": state, "rank": e.get("rank") or 0,
            "started": iso(started), "finished": iso(finished),
            "duration": round(minutes * 60) if minutes and state in DONE else None}


def parse_envs(rel):
    return sorted((parse_env(e) for e in rel.get("environments") or []), key=lambda e: e["rank"])


def release_state(rel, envs):
    if rel.get("status") == "abandoned":
        return "canceled"
    states = [e["state"] for e in envs]
    for s in ("running", "waiting", "queued"):
        if s in states:
            return s
    touched = [e for e in envs if e["state"] not in ("pending", "unknown")]
    # Result of the furthest environment that has been deployed; later ones may be manual
    return touched[-1]["state"] if touched else "pending"


def web_url(rel):
    return (rel.get("_links") or {}).get("web", {}).get("href")


def summarize_release(rel, envs):
    st = release_state(rel, envs)
    arts = rel.get("artifacts") or []
    art = next((a for a in arts if a.get("isPrimary")), arts[0] if arts else {})
    branch = ((art.get("definitionReference") or {}).get("branch") or {}).get("name") or ""
    live = next((e for e in envs if e["state"] in ACTIVE), None)
    finished = [e["finished"] for e in envs if e["finished"]]
    durations = [e["duration"] for e in envs if e["duration"]]
    return {
        "id": rel["id"],
        "number": rel.get("name"),
        "state": st,
        "branch": branch.removeprefix("refs/heads/"),
        "who": (rel.get("createdBy") or {}).get("displayName"),
        "reason": rel.get("reason"),
        "queued": iso(rel.get("createdOn")),
        # For a release deploying right now, time the environment, not the release:
        # a release created last week may only now be going to Prod.
        "started": live["started"] if live else iso(rel.get("createdOn")),
        "finished": max(finished) if finished and st not in ACTIVE else None,
        "duration": sum(durations) if durations and st not in ACTIVE else None,
        "activity": iso(rel.get("modifiedOn")),
        "url": web_url(rel),
        "stages": envs,
        "stage": live["name"] if live else None,
    }


def release_detail(project, release_id):
    return get(f"{VSRM}/{project}/_apis/release/releases/{release_id}")


def build_release(project, rel):
    envs = parse_envs(rel)
    raw = [e.get("status") for e in rel.get("environments") or []]
    if any(s in ("inProgress", "queued", "scheduled") for s in raw) or release_state(rel, envs) in ACTIVE:
        # The list view lacks deploy times and sometimes approvals; the full release has both
        try:
            rel = release_detail(project, rel["id"])
            envs = parse_envs(rel)
        except Exception as e:
            log.warning("release %s detail failed: %s", rel.get("id"), e)
    return summarize_release(rel, envs)


def poll_releases():
    out = []
    for project in PROJECTS:
        rels = get_paged(f"{VSRM}/{project}/_apis/release/releases", LOOKBACK_REL,
                         **{"$expand": "environments,artifacts,approvals", "queryOrder": "descending"})
        by_def, defs = defaultdict(list), {}
        for r in rels:
            d = r.get("releaseDefinition") or {}
            if "id" in d:
                by_def[d["id"]].append(r)
                defs[d["id"]] = d
        for def_id, runs in by_def.items():
            runs = runs[:HISTORY]
            out.append({
                "kind": "release",
                "project": project,
                "name": defs[def_id].get("name"),
                "folder": (defs[def_id].get("path") or "\\").strip("\\"),
                "latest": build_release(project, runs[0]),
                "history": [{"state": release_state(r, parse_envs(r)), "number": r.get("name"),
                             "url": web_url(r)} for r in reversed(runs[1:])],
            })
    # Newest activity first: a manual deploy to Prod today counts, even on an older release
    out.sort(key=lambda p: p["latest"]["activity"] or "", reverse=True)
    return out


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
        if RELEASES:
            try:
                rels = poll_releases()
                with lock:
                    state.update(releases=rels, release_error=None)
                log.info("polled %d release definitions", len(rels))
            except Exception as e:  # never let releases take the builds tab down with them
                log.error("release poll failed: %s", e)
                with lock:
                    state["release_error"] = str(e)
        time.sleep(POLL)


def stage_refresher():
    """Between full polls, refresh stages of running builds and active releases every STAGE_POLL seconds."""
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
        with lock:
            live_rel = [(p["project"], p["latest"]) for p in state["releases"]
                        if p["latest"]["state"] in ACTIVE]
        for project, latest in live_rel:
            try:
                rel = release_detail(project, latest["id"])
                fresh = summarize_release(rel, parse_envs(rel))
            except Exception as e:
                log.warning("release %s refresh failed: %s", latest["id"], e)
                continue
            with lock:
                latest.update(fresh)


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
