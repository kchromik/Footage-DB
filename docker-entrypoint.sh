#!/bin/sh
set -e

# Läuft der Container als root, passen wir den App-Benutzer an PUID/PGID an
# und starten die App danach ohne root-Rechte. So gehören Uploads auf dem NAS
# dem richtigen Benutzer.
if [ "$(id -u)" = "0" ]; then
    PUID="${PUID:-1000}"
    PGID="${PGID:-1000}"

    groupmod -o -g "$PGID" appuser 2>/dev/null || true
    usermod -o -u "$PUID" -g "$PGID" appuser 2>/dev/null || true

    # Zugriff auf die iGPU (VAAPI), falls /dev/dri durchgereicht wurde
    for dev in /dev/dri/render* /dev/dri/card*; do
        [ -e "$dev" ] || continue
        gid="$(stat -c '%g' "$dev")"
        gname="$(getent group "$gid" | cut -d: -f1)"
        if [ -z "$gname" ]; then
            gname="render$gid"
            groupadd -o -g "$gid" "$gname" 2>/dev/null || true
        fi
        usermod -aG "$gname" appuser 2>/dev/null || true
    done

    mkdir -p "${FDB_DATA_DIR:-/data}"
    chown appuser:appuser "${FDB_DATA_DIR:-/data}" 2>/dev/null || true
    # Unterordner nur anfassen, wenn sie noch nicht passen (spart Zeit bei
    # großen Datenverzeichnissen)
    find "${FDB_DATA_DIR:-/data}" -maxdepth 2 ! -user appuser -exec chown appuser:appuser {} + 2>/dev/null || true

    exec gosu appuser "$@"
fi

exec "$@"
