## Useful commands

Task	Command
Apply a change to app.py, index.html or azdo.env	sudo systemctl restart azdo-dashboard
Check whether it's running	sudo systemctl status azdo-dashboard --no-pager
Watch the live log	journalctl -u azdo-dashboard -f
Show recent log lines	journalctl -u azdo-dashboard -n 50 --no-pager
Stop it	sudo systemctl stop azdo-dashboard
Update from GitHub	cd /opt/azdo-dashboard && git pull && sudo systemctl restart azdo-dashboard
