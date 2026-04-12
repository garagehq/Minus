#!/bin/bash
# Autonomous Mode 24-hour Monitor
# Checks every 15 minutes for issues and logs status

LOG_FILE="/home/radxa/Minus/autonomous_monitor.log"
DURATION_HOURS=24
CHECK_INTERVAL=900  # 15 minutes in seconds

# Calculate end time
END_TIME=$(($(date +%s) + DURATION_HOURS * 3600))

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

check_status() {
    log "=== STATUS CHECK ==="

    # Get system resources
    MEM_INFO=$(free -h | grep Mem | awk '{print "Used:", $3, "/", $2}')
    MINUS_PROC=$(ps aux | grep -E "python.*minus" | grep -v grep | head -1)
    if [ -n "$MINUS_PROC" ]; then
        MINUS_PID=$(echo "$MINUS_PROC" | awk '{print $2}')
        MINUS_CPU=$(echo "$MINUS_PROC" | awk '{print $3}')
        MINUS_MEM=$(echo "$MINUS_PROC" | awk '{print $4}')
        MINUS_RSS=$(echo "$MINUS_PROC" | awk '{printf "%.0f", $6/1024}')
        log "System Memory: $MEM_INFO"
        log "Minus PID=$MINUS_PID CPU=${MINUS_CPU}% MEM=${MINUS_MEM}% RSS=${MINUS_RSS}MB"
    else
        log "ERROR: Minus process not running!"
        return 1
    fi

    # Check autonomous mode
    AUTO_STATUS=$(curl -s http://localhost:80/api/autonomous 2>/dev/null)
    if [ -z "$AUTO_STATUS" ]; then
        log "ERROR: Cannot reach API - web server down?"
        return 1
    fi

    ENABLED=$(echo "$AUTO_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('enabled', False))" 2>/dev/null)
    ACTIVE=$(echo "$AUTO_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('active', False))" 2>/dev/null)
    VIDEOS=$(echo "$AUTO_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stats',{}).get('videos_played',0))" 2>/dev/null)
    ERRORS=$(echo "$AUTO_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stats',{}).get('errors',0))" 2>/dev/null)
    DEVICE=$(echo "$AUTO_STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('device_type','?'), 'connected' if d.get('device_connected') else 'DISCONNECTED')" 2>/dev/null)

    log "Autonomous: enabled=$ENABLED active=$ACTIVE videos=$VIDEOS errors=$ERRORS device=$DEVICE"

    # Check VLM
    VLM_STATUS=$(curl -s http://localhost:80/api/vlm/status 2>/dev/null)
    VLM_LOADED=$(echo "$VLM_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('model_loaded', False))" 2>/dev/null)
    VLM_FRAMES=$(echo "$VLM_STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('frame_count', 0))" 2>/dev/null)
    log "VLM: loaded=$VLM_LOADED frames=$VLM_FRAMES"

    # Check health
    HEALTH=$(curl -s http://localhost:80/api/health 2>/dev/null)
    HEALTH_STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null)
    HDMI=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('hdmi_signal', False))" 2>/dev/null)
    ISSUES=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('issues', []))" 2>/dev/null)
    log "Health: status=$HEALTH_STATUS hdmi=$HDMI issues=$ISSUES"

    # Check for memory leak (RSS > 3GB is concerning)
    if [ "$MINUS_RSS" -gt 3000 ]; then
        log "WARNING: High memory usage (${MINUS_RSS}MB) - possible leak"
    fi

    # Check if autonomous mode stuck (enabled but not active for too long)
    if [ "$ENABLED" = "True" ] && [ "$ACTIVE" = "False" ]; then
        log "WARNING: Autonomous mode enabled but not active"
    fi

    log "---"
    return 0
}

restart_service() {
    log "Restarting minus service..."
    sudo systemctl restart minus
    sleep 10
    log "Service restarted"
}

# Main loop
log "=========================================="
log "Starting 24-hour autonomous mode monitor"
log "End time: $(date -d @$END_TIME)"
log "=========================================="

while [ $(date +%s) -lt $END_TIME ]; do
    if ! check_status; then
        log "Critical issue detected - attempting restart..."
        restart_service
    fi

    sleep $CHECK_INTERVAL
done

log "=========================================="
log "24-hour monitoring complete"
log "=========================================="
