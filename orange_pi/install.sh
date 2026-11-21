#!/bin/sh
set -eu

if [ "$(id -u)" -ne 0 ]; then
    printf '%s\n' 'Run with sudo only after authorizing package and service installation.' >&2
    exit 1
fi

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
apt-get update
apt-get install -y python3 python3-opencv v4l-utils
if ! getent passwd display-response >/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin --groups video display-response
fi
install -d -m 0755 /opt/display-response-agent
install -m 0644 "$source_dir/agent/server.py" /opt/display-response-agent/server.py
install -m 0644 "$source_dir/display-response-agent.service" /etc/systemd/system/display-response-agent.service
systemctl daemon-reload
systemctl enable display-response-agent.service
systemctl restart display-response-agent.service
systemctl --no-pager status display-response-agent.service