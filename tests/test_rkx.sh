#!/bin/bash
killall ustreamer gst-launch-1.0 2>/dev/null
fuser -k 9090/tcp 2>/dev/null
sleep 2

echo "Starting ustreamer..."
ustreamer --device=/dev/video0 --format=BGR24 --port=9090 --quality=50 --workers=6 --buffers=6 &
sleep 4

echo "Starting rkximagesink..."
DISPLAY=:0 gst-launch-1.0 souphttpsrc location=http://localhost:9090/stream ! multipartdemux ! jpegparse ! mppjpegdec ! rkximagesink sync=false &
sleep 5

echo "Making fullscreen..."
DISPLAY=:0 wmctrl -r :ACTIVE: -b add,fullscreen
sleep 3

echo "Measuring FPS..."
bytes=$(timeout 6 curl -s http://localhost:9090/stream | wc -c)
echo "Bytes in 5s: $bytes"
# Approximate FPS: bytes / (avg frame size ~150KB) / 5
echo "Approx FPS: $((bytes / 150000 / 5))"

echo "Done. Press Ctrl+C to stop."
wait
