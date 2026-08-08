#!/bin/bash
# Riffado watchdog — restarts the containers when port 3000 stops answering.
#
# Docker Desktop restarts (updates, crashes) can leave riffado-app/riffado-db
# exited despite their `unless-stopped` restart policy; every plaud worker run
# then crash-loops on "Connection refused" until someone notices (2026-08-08:
# down 17:55-21:23, caught by the EOD digest). Driven from launchd every 5 min
# (net.bhangar.riffado-watchdog); silent no-op while the app answers.
#
# If you deliberately want Riffado down, unload the agent first:
#   launchctl unload ~/Library/LaunchAgents/net.bhangar.riffado-watchdog.plist

set -u
PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# Any HTTP response (the app root 307-redirects) means alive.
if curl -s -o /dev/null --max-time 5 http://127.0.0.1:3000/; then
    exit 0
fi

log "port 3000 down — recovering"

if ! docker info >/dev/null 2>&1; then
    log "docker daemon unreachable — launching Docker Desktop"
    open -ga Docker
    for _ in $(seq 1 24); do
        sleep 5
        docker info >/dev/null 2>&1 && break
    done
    if ! docker info >/dev/null 2>&1; then
        log "docker daemon still unreachable after 120s — giving up until next check"
        exit 1
    fi
fi

# `docker start` on a running container is a no-op, but it doesn't honor the
# compose depends_on ordering — bring up the db and wait for health ourselves.
docker start riffado-db >/dev/null || { log "docker start riffado-db failed"; exit 1; }
for _ in $(seq 1 12); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' riffado-db 2>/dev/null)" = "healthy" ] && break
    sleep 5
done

docker start riffado-app >/dev/null || { log "docker start riffado-app failed"; exit 1; }
for _ in $(seq 1 12); do
    sleep 5
    if curl -s -o /dev/null --max-time 5 http://127.0.0.1:3000/; then
        log "recovered — riffado answering on port 3000"
        exit 0
    fi
done

log "containers started but port 3000 still not answering after 60s"
exit 1
