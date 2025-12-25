#!/bin/bash
killall ustreamer vlc mpv gst-launch-1.0 2>/dev/null
fuser -k /dev/video0 2>/dev/null
sleep 2

echo "=== Direct V4L2 capture to display (fastest path) ==="
echo "This bypasses HTTP entirely - direct capture to screen"

# Direct pipeline: V4L2 capture -> display
DISPLAY=:0 gst-launch-1.0 -v \
    v4l2src device=/dev/video0 ! \
    video/x-raw,format=BGR,width=3840,height=2160,framerate=30/1 ! \
    queue max-size-buffers=5 ! \
    videoconvert ! \
    autovideosink sync=false 2>&1 &
GST_PID=$!

sleep 5
DISPLAY=:0 wmctrl -r :ACTIVE: -b add,fullscreen 2>/dev/null
echo "Direct pipeline running. Watch the screen!"
sleep 15

if ps -p $GST_PID > /dev/null 2>&1; then
    echo "Pipeline still running"
else
    echo "Pipeline exited"
fi

killall gst-launch-1.0 2>/dev/null
echo "Done"
