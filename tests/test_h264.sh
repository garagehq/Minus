#!/bin/bash
killall ustreamer vlc mpv gst-launch-1.0 ffmpeg ffplay 2>/dev/null
fuser -k 9090/tcp 8080/tcp 2>/dev/null
sleep 2

echo "=== Testing H264 transcode pipeline ==="
echo "This transcodes MJPEG->H264 (using HW) then displays with HW decode"

# Start ustreamer
ustreamer --device=/dev/video0 --format=BGR24 --port=9090 --quality=50 --workers=6 --buffers=6 &
sleep 4
echo "ustreamer running"

# GStreamer pipeline: HTTP MJPEG -> HW JPEG decode -> HW H264 encode -> HW H264 decode -> display
echo "Starting GStreamer transcode + display pipeline..."
DISPLAY=:0 gst-launch-1.0 \
    souphttpsrc location=http://localhost:9090/stream ! \
    multipartdemux ! \
    jpegparse ! \
    mppjpegdec ! \
    queue max-size-buffers=30 max-size-time=1000000000 ! \
    mpph264enc ! \
    h264parse ! \
    mppvideodec ! \
    queue max-size-buffers=10 ! \
    autovideosink sync=false 2>&1 &
GST_PID=$!

sleep 5
DISPLAY=:0 wmctrl -r :ACTIVE: -b add,fullscreen 2>/dev/null
sleep 15

echo ""
if ps -p $GST_PID > /dev/null 2>&1; then
    echo "Pipeline still running"
else
    echo "Pipeline exited"
fi

killall gst-launch-1.0 ustreamer 2>/dev/null
echo "Done"
