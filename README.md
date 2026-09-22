# AzurePipelineDashboard

Azure Pipelines Live Dashboard

A small Flask app that shows the live state of your Azure DevOps pipelines on one page. It runs on a single Linux host and polls the Azure DevOps REST API. Anyone on the network can open it in a browser, which makes it a good fit for a wall display or a shared status page.

What it shows

Each pipeline gets one row, with the most recently queued run at the top. A row contains:

Status block: the latest run's result (Passed, Failed, Running, Queued, Partial, Canceled) and its build number. Clicking it opens the run in Azure DevOps.
Pipeline name, with its project and folder.
Branch and requester for the latest run.
Timing: a live elapsed timer and the current stage while a run is in progress, "waiting for an agent" while it is queued, and when it finished and how long it took once it is done.
History strip: one colored tick for each earlier run, oldest on the left. Each tick links to its run, so it is easy to tell a one-off failure from a streak.
Stage track: every stage of the latest run in order, colored by state. A running stage pulses and shows a timer, and a stage held at an approval gate is marked "awaiting approval". Classic pipelines, and YAML pipelines without stages, show their jobs instead.

The header summarizes the page, for example "2 running, 1 failing, 18 passing". When more than one project is configured, filter buttons appear, and the chosen filter is kept in the URL (/#project=Accounting) so a wall display can be pinned to one project. The page follows the viewer's light or dark system setting.

How it works
 Azure DevOps REST API
          ▲
          │  outbound HTTPS only, authenticated with a PAT
          │
 ┌────────┴───────────────────────────────┐
 │ Linux host (gunicorn, one worker)      │
 │                                        │
 │  poller thread ─ every 30 s: all runs  │
 │  stage thread  ─ every 5 s: stages of  │
 │                  in-progress runs      │
 │          │                             │
 │          ▼                             │
 │     in-memory cache                    │
 │          │                             │
 │   Flask: /  /api/state  /healthz       │
 └──────────┬─────────────────────────────┘
            │  port 5050
            ▼
   browsers (refresh every 5 s)

Browsers only ever read the cache, so ten people watching the page cost the same number of Azure DevOps API calls as one. Stage timelines of finished runs never change, so each one is fetched once and cached. If Azure DevOps can't be reached, the page keeps showing the last good data under a banner that explains what went wrong.

All traffic to Azure DevOps is outbound, so no inbound firewall rule from the internet is needed.

Requirements
A Linux host with Python 3.9 or newer (developed on Debian with Python 3.11)
Outbound HTTPS to dev.azure.com
An Azure DevOps personal access token (PAT) with the Build → Read scope and nothing more
Project layout
azdo-dashboard/
├── app.py                   # Flask app, poller and stage refresher
├── templates/
│   └── index.html           # The dashboard page (HTML, CSS and JS in one file)
├── requirements.txt         # flask, requests, gunicorn
├── azdo.env.example         # Configuration template; copy to azdo.env
├── azdo-dashboard.service   # systemd unit
├── docs/
│   └── TROUBLESHOOTING.md
└── .gitignore               # Keeps azdo.env (your PAT) out of git
