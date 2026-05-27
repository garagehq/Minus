#!/bin/bash
# Periodic minus health checkin. Runs ad_block_monitor.py over the last
# 30 min, appending the one-line row to tools/ad_block_baseline.md.
# On ATTN status, captures rich diagnostic context to
# tools/ad_block_diagnostics.md so the root cause can be reconstructed
# from the file alone in a future session.
#
# Wired into /etc/systemd/system/minus-monitor.timer (every 30 min).
# Safe to run manually any time.

set -u
REPO=/home/radxa/Minus
BASELINE="$REPO/tools/ad_block_baseline.md"
DIAG="$REPO/tools/ad_block_diagnostics.md"
WINDOW_MIN=30

cd "$REPO" || exit 1

# Run the monitor. Output also goes to its own log inside the tool.
OUT=$(python3 tools/ad_block_monitor.py --minutes "$WINDOW_MIN" 2>&1)
VERDICT=$(printf '%s\n' "$OUT" | awk -F': ' '/^VERDICT:/{print $2; exit}')
TS=$(date -u +'%Y-%m-%d %H:%M:%S UTC')

# Always print to stdout (captured by journalctl for the .service unit).
printf '%s\n' "$OUT"

# Clean ticks: monitor already appended to ad_block_baseline.md. Done.
case "$VERDICT" in
    OK|"")
        exit 0
        ;;
esac

# ATTN path: append a richer diagnostic snapshot. Future-claude reads
# this when checking in; the goal is enough context to root-cause
# without re-running anything.
{
    echo
    echo "## $TS — $VERDICT"
    echo
    echo '### Monitor report'
    echo '```'
    printf '%s\n' "$OUT"
    echo '```'
    echo
    echo '### /api/health snapshot'
    echo '```json'
    curl -s --max-time 5 http://localhost:80/api/health \
        | python3 -m json.tool 2>/dev/null \
        || echo '(unavailable)'
    echo '```'
    echo
    echo '### Axera NPU state (axcl-smi)'
    echo '```'
    {
        axcl-smi info --temp 2>&1
        axcl-smi info --npu  2>&1
        axcl-smi info --cmm  2>&1
    } | head -30
    echo '```'
    echo
    echo "### Recent minus errors (last ${WINDOW_MIN}m)"
    echo '```'
    sudo -n journalctl -u minus --no-pager --since "${WINDOW_MIN} minutes ago" 2>&1 \
        | grep -E '\[E\]|\[W\]|Traceback|restart|RESTART|TIMEOUT|KILLED|degraded|zombie|OOM|Killed' \
        | tail -80
    echo '```'
    echo
    echo '### Service status'
    echo '```'
    sudo -n systemctl status minus --no-pager 2>&1 | head -25
    echo '```'
    echo
} >> "$DIAG"

exit 0
