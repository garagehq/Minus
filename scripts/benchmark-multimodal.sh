#!/bin/bash
# benchmark-multimodal.sh - Benchmark RKLLM multimodal inference
# Run this on the Youyeetoo R1

set -e

# Find demo directory
DEMO_DIR=""
for dir in "$HOME/rknn-llm" "/root/rknn-llm"; do
    if [ -d "$dir/examples/multimodal_model_demo/deploy/install/demo_Linux_aarch64" ]; then
        DEMO_DIR="$dir/examples/multimodal_model_demo/deploy/install/demo_Linux_aarch64"
        break
    fi
done

if [ -z "$DEMO_DIR" ]; then
    echo "Demo directory not found"
    exit 1
fi

cd "$DEMO_DIR"

# Check for models
VISION_MODEL="models/internvl3-1b_vision_fp16_rk3588.rknn"
LLM_MODEL="models/internvl3-1b_w8a8_rk3588.rkllm"

if [ ! -f "$VISION_MODEL" ] || [ ! -f "$LLM_MODEL" ]; then
    echo "Models not found in $DEMO_DIR/models/"
    exit 1
fi

echo "=========================================="
echo "  RKLLM Multimodal Benchmark"
echo "=========================================="
echo ""
echo "Demo directory: $DEMO_DIR"
echo "Vision model: $VISION_MODEL"
echo "LLM model: $LLM_MODEL"
echo ""

# Create a simple test script using expect
if ! command -v expect &> /dev/null; then
    echo "Installing expect for automated testing..."
    sudo apt-get update && sudo apt-get install -y expect
fi

# Create expect script for automated prompts
cat > /tmp/benchmark_run.exp << 'EXPECT_SCRIPT'
#!/usr/bin/expect -f

set timeout 120
set demo_path [lindex $argv 0]
set prompt [lindex $argv 1]

cd $demo_path

spawn ./demo demo.jpg models/internvl3-1b_vision_fp16_rk3588.rknn models/internvl3-1b_w8a8_rk3588.rkllm 2048 4096 3 {<|vision_start|>} {<|vision_end|}> {<|image_pad|>}

# Wait for the prompt
expect "user:"

# Send the test prompt
send "$prompt\r"

# Wait for robot response to complete and next user prompt
expect {
    "user:" { }
    timeout { puts "Timeout waiting for response" }
}

# Exit
send "\003"
expect eof
EXPECT_SCRIPT

chmod +x /tmp/benchmark_run.exp

echo "=========================================="
echo "  Test 1: Simple description"
echo "=========================================="
echo "Prompt: <image>What is in the image?"
echo ""

START=$(date +%s.%N)
/tmp/benchmark_run.exp "$DEMO_DIR" "<image>What is in the image?" 2>&1 | tee /tmp/bench_output1.txt
END=$(date +%s.%N)
ELAPSED=$(echo "$END - $START" | bc)

echo ""
echo "Total time (including load): ${ELAPSED}s"
echo ""

# Extract just inference time by running again (model cached)
echo "=========================================="
echo "  Test 2: Yes/No question"
echo "=========================================="
echo "Prompt: <image>Is there a person in this image? Answer yes or no."
echo ""

START=$(date +%s.%N)
/tmp/benchmark_run.exp "$DEMO_DIR" "<image>Is there a person in this image? Answer yes or no." 2>&1 | tee /tmp/bench_output2.txt
END=$(date +%s.%N)
ELAPSED=$(echo "$END - $START" | bc)

echo ""
echo "Total time (including load): ${ELAPSED}s"
echo ""

echo "=========================================="
echo "  Test 3: Detailed description"
echo "=========================================="
echo "Prompt: <image>Describe this image in detail."
echo ""

START=$(date +%s.%N)
/tmp/benchmark_run.exp "$DEMO_DIR" "<image>Describe this image in detail." 2>&1 | tee /tmp/bench_output3.txt
END=$(date +%s.%N)
ELAPSED=$(echo "$END - $START" | bc)

echo ""
echo "Total time (including load): ${ELAPSED}s"
echo ""

echo "=========================================="
echo "  Summary"
echo "=========================================="
echo ""
echo "Note: Times include model loading (~2s). For inference-only timing,"
echo "run the demo interactively and time responses manually, or check"
echo "the source code at:"
echo "  ~/rknn-llm/examples/multimodal_model_demo/deploy/src/main.cc"
echo ""
echo "The demo prints load times. To measure token generation speed,"
echo "count output tokens and divide by response time."
echo ""

# Cleanup
rm -f /tmp/benchmark_run.exp /tmp/bench_output*.txt
