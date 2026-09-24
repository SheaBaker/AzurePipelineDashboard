# Installation

These steps install the dashboard to `/opt/azdo-dashboard`. The paths in the service file assume that location, so if you choose a different one, update the service file to match.

## 1. Get the code onto the host

```bash
sudo mkdir -p /opt/azdo-dashboard
sudo chown -R "$USER": /opt/azdo-dashboard
git clone https://github.com/SheaBaker/AzurePipelineDashboard.git /opt/azdo-dashboard
```

Use `chown -R`, not a plain `chown`. Without `-R`, subfolders created with `sudo` stay owned by root, and later copies into them fail with "Permission denied".

## 2. Create a virtual environment and install dependencies

```bash
cd /opt/azdo-dashboard
python3 -m venv /opt/azdo-dashboard/venv
/opt/azdo-dashboard/venv/bin/pip install -r /opt/azdo-dashboard/requirements.txt
```

## 3. Create a personal access token

In Azure DevOps, open **User settings → Personal access tokens → New Token** and grant only these scopes:

- **Build → Read**, for the Builds tab
- **Release → Read**, for the Releases tab

Set an expiry you'll remember to renew. The dashboard shows a clear banner when the token expires or lacks a scope. If you add a scope to an existing token later, the token value doesn't change, so `azdo.env` needs no update.

Treat the token like a password. Don't paste it into screenshots, tickets or chat. If it's ever exposed, revoke it and create a new one.

## 4. Configure

```bash
cp /opt/azdo-dashboard/azdo.env.example /opt/azdo-dashboard/azdo.env
chmod 600 /opt/azdo-dashboard/azdo.env
vi /opt/azdo-dashboard/azdo.env
```

| Setting | Default | Purpose |
|---|---|---|
| `AZDO_ORG` | *(required)* | Organization name, the part after `https://dev.azure.com/` |
| `AZDO_PROJECTS` | *(required)* | Comma-separated project names, exactly as shown in Azure DevOps. **Wrap the value in double quotes** if any name contains a space |
| `AZDO_PAT` | *(required)* | Personal access token with Build (Read) and Release (Read) scopes |
| `POLL_SECONDS` | `30` | Seconds between full polls of every project |
| `STAGE_POLL_SECONDS` | `5` | Seconds between refreshes of in-progress builds and active releases |
| `HISTORY_RUNS` | `12` | Earlier runs shown in each history strip |
| `LOOKBACK_BUILDS` | `300` | Most recent builds fetched per project. Raise it if rarely run pipelines are missing |
| `LOOKBACK_RELEASES` | `200` | Most recent classic releases fetched per project |
| `ENABLE_RELEASES` | `true` | Set to `false` to stop polling classic releases |
| `PORT` | `5050` | Port for the foreground test in step 5 only. The service's port is set in `azdo-dashboard.service` |

To check the file without showing the token on screen:

```bash
grep -v PAT /opt/azdo-dashboard/azdo.env
```

## 5. Test in the foreground

```bash
set -a; . /opt/azdo-dashboard/azdo.env; set +a
/opt/azdo-dashboard/venv/bin/python /opt/azdo-dashboard/app.py
```

Within a few seconds the log should show two lines like these:

```
polled 14 pipelines across 4 project(s)
polled 9 release definitions
```

Browse to `http://<host>:5050`. When the page looks right, press **Ctrl+C**.

## 6. Install the systemd service

Set the service account to the user that owns `/opt/azdo-dashboard`, then install and start the service. Replace `ansible` with your account name:

```bash
sed -i 's/^User=.*/User=ansible/' /opt/azdo-dashboard/azdo-dashboard.service
grep ^User /opt/azdo-dashboard/azdo-dashboard.service
sudo cp /opt/azdo-dashboard/azdo-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now azdo-dashboard
sudo systemctl status azdo-dashboard --no-pager
```

The `grep` must print `User=<your account>` before you continue. The status should show `active (running)`. From now on the dashboard starts at boot and restarts itself if it crashes.

## 7. Open the firewall if needed

If the page doesn't load from another machine but the service is running, allow the port:

```bash
# Debian / Ubuntu with ufw
sudo ufw allow 5050/tcp

# RHEL family with firewalld
sudo firewall-cmd --add-port=5050/tcp --permanent && sudo firewall-cmd --reload
```

If users on another network segment need access, also allow TCP 5050 from their subnets to this host's IP on the firewall between the segments. Make sure they can resolve the host's name as well: use its full DNS name, or add a DNS record on their side.

Next, see [operating.md](operating.md) for day-to-day commands.
