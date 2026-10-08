#!/bin/sh
# Install only the HyperChE virtual host. Existing API sites are left intact.
set -eu
if [ "$(id -u)" != 0 ]; then
    echo "Run this host Nginx configuration step as root." >&2
    exit 1
fi
mode=${1:-https}
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
target=/etc/nginx/sites-available/hyperche.fallrain0905.top.conf
enabled=/etc/nginx/sites-enabled/hyperche.fallrain0905.top.conf
case "$mode" in
    http) source="$repo_dir/deploy/nginx.host.http.conf" ;;
    https)
        source="$repo_dir/deploy/nginx.host.https.conf"
        for cert_file in fullchain.pem privkey.pem; do
            if [ ! -s "/etc/letsencrypt/live/hyperche.fallrain0905.top/$cert_file" ]; then
                echo "Obtain the HyperChE TLS certificate before installing HTTPS." >&2
                exit 1
            fi
        done
        ;;
    *) echo "Usage: $0 [http|https]" >&2; exit 1 ;;
esac
if [ -e "$enabled" ] && { [ ! -L "$enabled" ] || [ "$(readlink "$enabled")" != "$target" ]; }; then
    echo "The HyperChE enabled-site path is occupied by another configuration." >&2
    exit 1
fi
backup=""
had_enabled=0
if [ -L "$enabled" ]; then
    had_enabled=1
fi
if [ -e "$target" ]; then
    backup="$target.backup.$(date -u +%Y%m%dT%H%M%SZ)"
    cp -p "$target" "$backup"
fi
mkdir -p /var/www/hyperche-acme
install -m 0644 "$source" "$target"
ln -sfn "$target" "$enabled"
if nginx -t; then
    systemctl reload nginx
    echo "Installed HyperChE $mode virtual host."
else
    if [ -n "$backup" ]; then
        cp -p "$backup" "$target"
        if [ "$had_enabled" = 0 ]; then
            rm -f "$enabled"
        fi
    else
        rm -f "$enabled" "$target"
    fi
    echo "Nginx rejected the new HyperChE configuration; prior files restored." >&2
    exit 1
fi
