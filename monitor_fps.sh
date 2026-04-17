#!/bin/bash
# FPS Monitoring Script - runs for 300 minutes (5 hours)
# Logs FPS every 60 seconds and alerts if FPS drops below 25

LOG_FILE="/tmp/minus_fps_monitor.log"
ALERT_THRESHOLD=25
DURATION_MINUTES=300
CHECK_INTERVAL=60

echo "$(date '+%Y-%m-%d %H:%M:%S') Starting FPS monitor for $DURATION_MINUTES minutes" | tee -a $LOG_FILE
echo "Alert threshold: FPS < $ALERT_THRESHOLD" | tee -a $LOG_FILE

start_time=$(date +%s)
end_time=$((start_time + DURATION_MINUTES * 60))

while [ $(date +%s) -lt $end_time ]; do
    fps=$(curl -s http://localhost/api/status 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('fps',0))" 2>/dev/null)

    if [ -z "$fps" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: Could not get FPS" | tee -a $LOG_FILE
    else
        fps_int=$(echo "$fps" | cut -d. -f1)
        if [ "$fps_int" -lt "$ALERT_THRESHOLD" ] 2>/dev/null; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') ALERT: FPS=$fps (below $ALERT_THRESHOLD)" | tee -a $LOG_FILE
        else
            echo "$(date '+%Y-%m-%d %H:%M:%S') OK: FPS=$fps" | tee -a $LOG_FILE
        fi
    fi

    sleep $CHECK_INTERVAL
done

echo "$(date '+%Y-%m-%d %H:%M:%S') Monitoring complete" | tee -a $LOG_FILE
