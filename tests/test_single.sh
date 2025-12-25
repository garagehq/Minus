#!/bin/bash
killall ustreamer gst-launch-1.0 2>/dev/null
fuser -k 9090/tcp 2>/dev/null
sleep 2

echo "=== Single Client Test (no measurement during display) ==="
ustreamer --device=/dev/video0 --format=BGR24 --port=9090 --quality=50 --workers=6 --buffers=6 &
sleep 3

# First: measure stream-only FPS
echo "Stream-only FPS (no display):"
python3 -c "
import urllib.request, time
start = time.time()
data = b''
with urllib.request.urlopen('http://localhost:9090/stream', timeout=6) as r:
    while time.time() - start < 5:
        data += r.read(8192)
print(f'{data.count(chr(0xff).encode() + chr(0xd8).encode())} frames in 5s')
" 2>/dev/null

# Now start display WITHOUT measurement
echo ""
echo "Starting rkximagesink display (10 seconds, check visually)..."
DISPLAY=:0 timeout 12 gst-launch-1.0 souphttpsrc location=http://localhost:9090/stream ! multipartdemux ! jpegparse ! mppjpegdec ! rkximagesink sync=false &
sleep 3
DISPLAY=:0 wmctrl -r :ACTIVE: -b add,fullscreen 2>/dev/null

echo "Display running - watch the screen for smoothness!"
echo "Waiting 8 seconds..."
sleep 8

killall gst-launch-1.0 ustreamer 2>/dev/null
echo "Test complete - did it look smooth (close to 30fps)?"
