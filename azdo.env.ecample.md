### Azure Pipelines dashboard configuration
### Copy to /opt/azdo-dashboard/azdo.env and run: chmod 600 /opt/azdo-dashboard/azdo.env
### NEVER commit the real azdo.env. It contains your PAT and is listed in .gitignore.

### Organization name: the part after https://dev.azure.com/
AZDO_ORG=your-org-name

### Comma-separated project names, exactly as shown in Azure DevOps.
### Keep the double quotes: they are required when any name contains a space.
AZDO_PROJECTS="Project One,Project Two"

### Personal access token with ONLY the Build (Read) scope
AZDO_PAT=paste-pat-here

### Seconds between full polls of every project
POLL_SECONDS=30

### Seconds between stage refreshes for runs that are in progress
STAGE_POLL_SECONDS=5

### Earlier runs shown in each pipeline's history strip
HISTORY_RUNS=12

### Most recent builds fetched per project each poll.
### Pipelines with no run inside this window do not appear on the dashboard.
LOOKBACK_BUILDS=300
