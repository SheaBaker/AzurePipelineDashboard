# Azure Pipelines Live Dashboard

A self-hosted status page for Azure DevOps. It shows every build pipeline and classic release pipeline across your projects on one screen, updating live. It's built with Python and Flask, polls the Azure DevOps REST APIs, and runs as a systemd service on a single Linux host. Anyone on the network can open it in a browser, which makes it a good fit for a wall display or a shared team page.

### Why I built it
Azure DevOps shows pipeline status one project and one pipeline at a time. With hundreds of pipelines spread across several projects, answering "what's running, what's failing, and what's waiting on an approval?" meant clicking through a lot of pages. This dashboard puts the answer on one screen that the whole team can keep open.

### Features
The header has two switches, and every combination works:
#### Board
- Builds: One row per build or YAML pipeline, with its latest run's status, stages and history
- Releases: Running builds drawn as connected stage nodes with live timers
#### Live Flow
- Builds: One row per classic release definition, with its environments as stages
- Releases: Deploying and approval-held releases drawn as connected environment nodes

## Board view 
### Each row shows:
**Status block**: 
- The latest result (Passed, Failed, Running or Deploying, Queued, Partial, Canceled, Awaiting approval, Not deployed) and    its build or release number. Clicking it opens the run in Azure DevOps.
- Name, project and folder of the pipeline or release definition.

**Branch and requester** of the latest run.

**Timing**: a live elapsed timer while running, the wait time while queued, and how long ago it finished and how long it took once it's done.

**Stage track**: every stage (builds) or environment (releases) in order, colored by state. The running stage pulses, and stages held at an approval gate are marked. Classic builds, and YAML pipelines without stages, show their jobs instead.

**History strip**: one colored tick per earlier run, oldest on the left. Each tick links to its run, so a one-off failure is easy to tell apart from a streak.

## Live flow view. 
A dark panel shows each run or release in progress as a lane of connected nodes. Completed stages get a check, the active stage pulses with a traveling marker toward the next stage, and approval gates are dashed amber. When nothing is active, the panel shows the three most recent runs. 

### Below it you get:
**Tiles** for success rate, average duration and active alerts, recalculated for the current filters.

A **branch filter** and a **"Failing only"** toggle.

**A recent activity log** listing each run's number, branch, requester and status.

## On both views:
**Project filter buttons** appear when more than one project is configured.

**Newest first.** Builds are sorted by when their latest run was queued. Releases are sorted by their latest activity, so a deploy to Prod today moves an older release to the top.

**The view is kept in the URL**, so a wall display can be pinned to one. For example, #src=releases&view=flow&project=Accounting opens the Live flow view for releases, filtered to the Accounting project.

**Light and dark mode** follow the viewer's system setting.

**Outages don't blank the page.** If Azure DevOps can't be reached, the page keeps showing the last good data under a banner that explains what went wrong.

**How release status is decided:** 
A release shows the result of the furthest environment it has been deployed to. Later environments are often manual, so a release that has only reached Dev shows Dev's result. A pending manual approval shows as Awaiting approval. "Took" adds up the environments' actual deploy time and leaves out time spent waiting on approvals.

**All traffic to Azure DevOps is outbound, so no inbound firewall rule from the internet is needed.**

<img width="452" height="784" alt="image" src="https://github.com/user-attachments/assets/f2df4991-2bf0-4646-b4b2-f0ae15980f0f" />
**Browsers only read the cache.** Ten people watching the page cost the same number of Azure DevOps API calls as one.

**Finished work is cached.** A finished build's stage timeline never changes, so it is fetched once. Full release details are fetched only for releases that are deploying or awaiting approval.

**Builds and releases fail independently.** If the releases poll fails, for example because the PAT lacks the Release scope, the Releases tab shows a banner and the Builds tab keeps working normally.

**Only outbound traffic.** The host makes outbound HTTPS calls to Azure DevOps, so no inbound firewall rule from the internet is needed.

## Tech stack
Python 3, Flask, Requests, gunicorn and systemd on the server. The front end is plain HTML, CSS and JavaScript in one template, with no framework or build step. It uses the Azure DevOps REST API 7.1: Builds, build timelines, and classic Releases, following the continuation tokens that the Releases API uses to page through results.
<img width="464" height="420" alt="image" src="https://github.com/user-attachments/assets/daea89f1-e410-4095-af68-779e4b5cd4f3" />

## Getting started
### You need three things:
  - A Linux host with Python 3.9 or newer. It was developed on Debian with Python 3.11.
  - Outbound HTTPS to dev.azure.com and vsrm.dev.azure.com.
  - An Azure DevOps personal access token with only the Build → Read and Release → Read scopes.

Follow Installation.md to set it up. Once it's running, operating.md covers the day-to-day commands, and docs/TROUBLESHOOTING.md covers what to do when something goes wrong.

### Security
- The PAT lives in azdo.env, which is chmod 600 and listed in .gitignore. Never commit it.
- The PAT needs only Build (Read) and Release (Read). Don't give it broader scopes.
- The dashboard has no login. Anyone who can reach port 5050 can see pipeline names, branches and who triggered each run.
- Keep it on an internal network, or put it behind a reverse proxy with authentication if that exposure matters.
- All names from Azure DevOps are HTML-escaped before they're displayed.

### Limitations
- Only recent activity appears. Each poll fetches the most recent LOOKBACK_BUILDS builds and LOOKBACK_RELEASES releases per project. A pipeline with no activity inside that window doesn't appear.
- Progress is shown as elapsed time, not a percentage. Azure DevOps doesn't report how far along a stage is, so the dashboard doesn't make one up.
- Run with one gunicorn worker. Each extra worker would start its own pollers and multiply the API calls.
