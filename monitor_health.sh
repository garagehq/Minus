#!/bin/bash
# Health monitoring script - runs every 5 minutes
# Checks for VLM timeouts, FPS drops, and other issues

LOG_FILE="/tmp/minus_health_monitor.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1"
}

check_health() {
    log "=== Health Check ==="

    # Get status from API
    STATUS=$(curl -s http://localhost/api/status 2>/dev/null)
    if [ -z "$STATUS" ]; then
        log "ERROR: Cannot reach API"
        return
    fi

    # Parse status
    FPS=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('fps', 0))" 2>/dev/null)
    VLM_READY=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('vlm_ready', False))" 2>/dev/null)
    BLOCKING=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('blocking', False))" 2>/dev/null)
    SOURCE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('blocking_source', 'None'))" 2>/dev/null)

    log "FPS: $FPS | VLM Ready: $VLM_READY | Blocking: $BLOCKING | Source: $SOURCE"

    # Check FPS
    FPS_INT=${FPS%.*}
    if [ "$FPS_INT" -lt 20 ] 2>/dev/null; then
        log "WARNING: Low FPS ($FPS)"
    fi

    # Check VLM timeouts in last 5 minutes
    VLM_TIMEOUTS=$(journalctl -u minus --since "5 minutes ago" --no-pager 2>/dev/null | grep -c "VLM.*timeout\|VLM.*error" || echo 0)
    VLM_TOTAL=$(journalctl -u minus --since "5 minutes ago" --no-pager 2>/dev/null | grep -c "VLM #" || echo 0)

    log "VLM: $VLM_TIMEOUTS timeouts / $VLM_TOTAL total in last 5 min"

    if [ "$VLM_TIMEOUTS" -gt 10 ]; then
        log "WARNING: High VLM timeout rate"
    fi

    # Check for OCR+VLM blocking
    OCR_VLM_COUNT=$(journalctl -u minus --since "5 minutes ago" --no-pager 2>/dev/null | grep -c "BLOCKING OCR+VLM" || echo 0)
    OCR_ONLY_COUNT=$(journalctl -u minus --since "5 minutes ago" --no-pager 2>/dev/null | grep -c "BLOCKING OCR\]" || echo 0)
    VLM_ONLY_COUNT=$(journalctl -u minus --since "5 minutes ago" --no-pager 2>/dev/null | grep -c "BLOCKING VLM\]" || echo 0)

    log "Blocking stats: OCR=$OCR_ONLY_COUNT, VLM=$VLM_ONLY_COUNT, OCR+VLM=$OCR_VLM_COUNT"

    # Check for errors
    ERRORS=$(journalctl -u minus --since "5 minutes ago" --no-pager 2>/dev/null | grep -c "\[E\]" || echo 0)
    log "Errors in last 5 min: $ERRORS"

    # Check VLM confirmation working
    VLM_CONFIRMS=$(journalctl -u minus --since "5 minutes ago" --no-pager 2>/dev/null | grep -c "VLM confirming" || echo 0)
    log "VLM confirmations: $VLM_CONFIRMS"

    log "=== End Health Check ==="
    echo "" >> "$LOG_FILE"
}

# Run once immediately
check_health

# Then loop every 5 minutes
while true; do
    sleep 300
    check_health
done
