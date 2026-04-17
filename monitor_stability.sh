#!/bin/bash
# Stability monitor - checks every 5 minutes for 3 hours
LOG="/tmp/minus_stability.log"
DURATION=$((3 * 60))  # 3 hours in minutes
INTERVAL=5            # 5 minutes

echo "$(date '+%Y-%m-%d %H:%M:%S') Starting 3-hour stability monitor (check every 5 min)" | tee $LOG

end_time=$(($(date +%s) + DURATION * 60))

while [ $(date +%s) -lt $end_time ]; do
    status=$(curl -s http://localhost/api/status 2>/dev/null)
    if [ -z "$status" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ERROR: API not responding" | tee -a $LOG
    else
        fps=$(echo "$status" | python3 -c "import sys,json; print(f\"{json.load(sys.stdin).get('fps',0):.1f}\")" 2>/dev/null)
        vlm=$(echo "$status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('vlm_ready',False))" 2>/dev/null)
        uptime=$(echo "$status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('uptime',0))" 2>/dev/null)
        
        # Check for issues
        fps_int=${fps%.*}
        if [ "$fps_int" -lt 25 ] 2>/dev/null; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') ALERT: FPS=$fps VLM=$vlm uptime=${uptime}s" | tee -a $LOG
        else
            echo "$(date '+%Y-%m-%d %H:%M:%S') OK: FPS=$fps VLM=$vlm uptime=${uptime}s" | tee -a $LOG
        fi
    fi
    
    # Check VLM for kills/timeouts in last 5 min
    kills=$(sudo journalctl -u minus --since "5 minutes ago" 2>/dev/null | grep -c "KILLED\|TIMEOUT" || echo 0)
    if [ "$kills" -gt 0 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') WARNING: $kills VLM kills/timeouts in last 5 min" | tee -a $LOG
    fi
    
    sleep $((INTERVAL * 60))
done

echo "$(date '+%Y-%m-%d %H:%M:%S') Monitoring complete" | tee -a $LOG
