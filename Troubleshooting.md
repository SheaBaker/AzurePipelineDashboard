# Troubleshooting

Each entry lists the symptom, its cause and the fix. Most come from the original deployment.

Start with the service log. It usually names the problem directly:

```bash
journalctl -u azdo-dashboard -n 50 --no-pager
```

## Service won't start

### `status=217/USER`

systemd can't find the account named on the `User=` line of the unit file. This usually means the placeholder `YOUR_USER` was never replaced, or the `sed` meant to replace it didn't match.

Fix the installed copy directly, then confirm:

```bash
sudo sed -i 's/^User=.*/User=ansible/' /etc/systemd/system/azdo-dashboard.service
grep ^User /etc/systemd/system/azdo-dashboard.service
sudo systemctl daemon-reload && sudo systemctl restart azdo-dashboard
```

Copy the corrected unit back so a reinstall doesn't bring the problem back:

```bash
sudo cp /etc/systemd/system/azdo-dashboard.service /opt/azdo-dashboard/azdo-dashboard.service
```

### `Unit azdo-dashboard.service not found`

The service hasn't been installed yet. Follow step 6 of [Installation.md](../Installation.md).

### `Address already in use`

Something else is on port 5050. That's often a foreground test still running in another terminal. Stop it with **Ctrl+C**, or find it:

```bash
sudo ss -ltnp | grep 5050
```

## Configuration errors

### `KeyError: 'AZDO_PROJECTS'`, with `command not found` just before it

A project name contains a space and the value isn't quoted. When the shell loads the file, it takes the value only up to the first space, tries to run the rest as a command, and never sets the variable. Quote the value:

```bash
sed -i 's/^AZDO_PROJECTS=\(.*\)$/AZDO_PROJECTS="\1"/' /opt/azdo-dashboard/azdo.env
grep AZDO_PROJECTS /opt/azdo-dashboard/azdo.env
```

systemd reads the quotes correctly too.

### Banner: "Azure DevOps rejected the PAT"

The token has expired, was revoked, or lacks a scope it needs: Build (Read) for builds, Release (Read) for releases. Azure DevOps answers a bad token with a `203` and a sign-in page rather than a `401`, and the app reports either case clearly. Create a new token, then:

```bash
sed -i 's/^AZDO_PAT=.*/AZDO_PAT=NEWTOKEN/' /opt/azdo-dashboard/azdo.env
sudo systemctl restart azdo-dashboard
```

### The Releases tab shows a banner but Builds works

The builds and releases polls run separately, so this usually means only the release side has a problem. Check the log:

```bash
journalctl -u azdo-dashboard -n 50 --no-pager | grep -i release
```

- **`rejected the PAT` or `401`:** the token lacks **Release → Read**. Edit the token in Azure DevOps, tick the scope and save. The token value doesn't change, so no config edit is needed. Then restart the service.
- **`404` for one project:** classic releases may be turned off for that project, or the project name is misspelled.
- **`400`:** the Releases API rejected the request, which can happen on older Azure DevOps Server versions. Check the API version your server supports.

If you don't use classic release pipelines at all, set `ENABLE_RELEASES=false` in `azdo.env` and restart.

### A pipeline or release is missing from the page

Only the most recent `LOOKBACK_BUILDS` builds (default 300) and `LOOKBACK_RELEASES` releases (default 200) per project are fetched. A pipeline or release definition with no activity inside that window doesn't appear. Raise the value in `azdo.env` and restart.

Also check that the project name in `AZDO_PROJECTS` exactly matches the name in Azure DevOps.

## Page problems

### The page doesn't load, but the log shows `polled ...` lines

The host firewall, or a firewall between network segments, is blocking port 5050. See step 7 of [Installation.md](../Installation.md).

### The page loads, but stages or other new features are missing

The browser is showing a cached copy of the old page. Hard-refresh with **Ctrl+F5**.

### A release shows "Not deployed"

None of its environments has been deployed yet. This is common when every environment, even the first, is triggered manually. It changes as soon as a deployment starts.

### A stage at an approval gate shows "Not started"

For **builds**, approval detection relies on the in-progress `Checkpoint` record that Azure DevOps adds to the run's timeline. If your organization's checks are recorded differently, look at one waiting run's timeline to see what's there:

```
https://dev.azure.com/<org>/<project>/_apis/build/builds/<buildId>/timeline?api-version=7.1
```

For **releases**, an environment counts as awaiting approval when it has a pending manual pre- or post-deployment approval.

## Host problems

### `No space left on device`

The disk is full. On a small VM the systemd journal is the usual thing that grows. Check usage, trim the journal and clear the package cache:

```bash
df -h /
sudo du -xh / --max-depth=2 2>/dev/null | sort -h | tail -15
sudo journalctl --vacuum-size=100M
sudo apt-get clean
```

Cap the journal permanently:

```bash
sudo sed -i 's/^#\?SystemMaxUse=.*/SystemMaxUse=200M/' /etc/systemd/journald.conf
sudo systemctl restart systemd-journald
```

A write that fails while the disk is full can leave behind **zero-byte files**. An empty `app.py` still passes `py_compile`, and running it simply exits without output. After freeing space, check the file sizes:

```bash
wc -l /opt/azdo-dashboard/app.py /opt/azdo-dashboard/templates/index.html
```

If either shows `0`, restore both with `git checkout -- app.py templates/index.html`.

### `Permission denied` when copying or extracting into `/opt/azdo-dashboard`

A subfolder was created with `sudo` and is still owned by root. Take ownership of the whole tree:

```bash
sudo chown -R "$USER": /opt/azdo-dashboard
```

## Getting files onto the host

Cloning the repository with git is the most reliable method. If the host can't reach GitHub, copy the files from a workstation with WinSCP, `pscp` (it ships with PuTTY) or `scp`. Avoid pasting large base64 blobs into a terminal: a single wrong character silently corrupts the whole archive.
