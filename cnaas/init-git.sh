#!/bin/sh
# cnaas-git: turns the mounted template/etc directories into git repos and serves them (plus the
# orchestrator-generated settings repo) over git:// to the CNaaS containers.
set -eu
apk add --no-cache git git-daemon gettext >/dev/null
git config --global user.email wfo@campus.local
git config --global user.name "Wired Orchestrator"
git config --global init.defaultBranch master
git config --global --add safe.directory '*'

publish() {  # publish <src dir> <bare repo>
  src=$1; bare=$2; work=$(mktemp -d)
  [ -d "$bare" ] || git init -q --bare "$bare"
  cp -r "$src"/. "$work"/
  cd "$work"; git init -q; git add -A; git commit -q -m "publish $(date -Iseconds)" || true
  git push -q -f "$bare" HEAD:master; cd /; rm -rf "$work"
}

publish /src/templates /git/templates.git
mkdir -p /tmp/etc/dhcpd
envsubst < /src/etc/dhcpd/dhcpd.conf.tmpl > /tmp/etc/dhcpd/dhcpd.conf
publish /tmp/etc /git/etc.git

if [ ! -d /git/settings.git ]; then
  git init -q --bare /git/settings.git
  work=$(mktemp -d); cd "$work"; git init -q
  mkdir -p global; printf -- "---\n" > global/base_system.yml
  git add -A; git commit -q -m "empty settings (orchestrator regenerates from NetBox)"
  git push -q /git/settings.git HEAD:master; cd /; rm -rf "$work"
fi
chown -R 1000:1000 /git/settings.git  # the orchestrator container commits as uid 1000
touch /git/ready
exec git daemon --reuseaddr --base-path=/git --export-all --enable=receive-pack --verbose /git
