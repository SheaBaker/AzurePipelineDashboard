# Operating the dashboard

## Everyday commands

| Task | Command |
|---|---|
| Apply a change to `app.py`, `templates/index.html` or `azdo.env` | `sudo systemctl restart azdo-dashboard` |
| Check whether it's running | `sudo systemctl status azdo-dashboard --no-pager` |
| Watch the live log | `journalctl -u azdo-dashboard -f` |
| Show recent log lines | `journalctl -u azdo-dashboard -n 50 --no-pager` |
| Stop it | `sudo systemctl stop azdo-dashboard` |

A restart is needed after any change, including a change to the page. Flask caches the template in memory until the service restarts. Afterward, hard-refresh the browser with **Ctrl+F5**.

## Updating from GitHub

```bash
cd /opt/azdo-dashboard && git pull && sudo systemctl restart azdo-dashboard
```

Your `azdo.env` is listed in `.gitignore`, so `git pull` never touches it.

## Healthy log output

Every poll, which is every 30 seconds by default, writes one line for builds and one for releases:

```
INFO polled 204 pipelines across 5 project(s)
INFO polled 190 release definitions
```

Errors show up as `poll failed: ...` for builds or `release poll failed: ...` for releases. See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Adding or removing a project

Edit `AZDO_PROJECTS` in `azdo.env`, keeping the double quotes, then restart:

```bash
grep AZDO_PROJECTS /opt/azdo-dashboard/azdo.env
sudo systemctl restart azdo-dashboard
```

Use each project's name exactly as Azure DevOps shows it. A single misspelled name makes that whole poll fail with a 404. The page keeps showing the last good data until you fix the name.

## Rotating the PAT

Create a new token with the same two scopes (Build → Read and Release → Read), then swap it in:

```bash
sed -i 's/^AZDO_PAT=.*/AZDO_PAT=NEWTOKEN/' /opt/azdo-dashboard/azdo.env
sudo systemctl restart azdo-dashboard
```

## HTTP endpoints

| Path | Returns |
|---|---|
| `/` | The dashboard page |
| `/api/state` | The cached data as JSON: `pipelines` (builds), `releases`, `updated`, `error` and `release_error`. Other tools can read this instead of calling Azure DevOps themselves |
| `/healthz` | `200` with `{"ok": true, "updated": ...}` once the first poll has finished, `503` before that. `ok` turns `false` if the latest builds poll failed. Suitable for a monitoring check |

## URL options

The page keeps its view in the part of the URL after `#`, so a link or wall display can open straight to it:

| Parameter | Values | Effect |
|---|---|---|
| `src` | `releases` | Opens the Releases tab. Builds is the default |
| `view` | `flow` | Opens the Live flow view. Board is the default |
| `project` | a project name | Filters to one project |

For example, `http://<host>:5050/#src=releases&view=flow&project=Accounting` opens the Live flow view for releases, filtered to the Accounting project.
