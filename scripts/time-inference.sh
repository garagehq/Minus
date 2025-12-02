#!/bin/bash
# time-inference.sh - Simple wrapper to time interactive prompts
# Usage: source this, then use 'timeit' function in the demo

# Simple timing function - paste this into the demo session
cat << 'EOF'
========================================
  Manual Inference Timing
========================================

Since the demo is interactive, here's how to time it manually:

METHOD 1: Time the whole demo startup + one query
-------------------------------------------------
time (echo "0" | timeout 60 ./demo demo.jpg models/internvl3-1b_vision_fp16_rk3588.rknn models/internvl3-1b_w8a8_rk3588.rkllm 2048 4096 3 '<|vision_start|>' '<|vision_end|>' '<|image_pad|>')

This times: model load + vision encode + LLM inference


METHOD 2: Interactive with timestamps
-------------------------------------
Run the demo normally, then for each prompt note the time:

  # Before typing prompt
  date +%s.%N

  # Type your prompt, wait for response

  # After response completes
  date +%s.%N

  # Calculate: end - start = inference time


METHOD 3: Use 'time' command for single query
---------------------------------------------
# Pipe a single prompt (uses preset 0)
echo "0" | ./demo demo.jpg models/internvl3-1b_vision_fp16_rk3588.rknn models/internvl3-1b_w8a8_rk3588.rkllm 2048 4096 3 '<|vision_start|>' '<|vision_end|>' '<|image_pad|>' 2>&1 | head -50

# With timing:
time (echo "0" | ./demo demo.jpg models/internvl3-1b_vision_fp16_rk3588.rknn models/internvl3-1b_w8a8_rk3588.rkllm 2048 4096 3 '<|vision_start|>' '<|vision_end|>' '<|image_pad|>' 2>&1)


METHOD 4: Quick tokens/second estimate
--------------------------------------
1. Run a prompt that generates ~50-100 tokens
2. Time how long the response takes
3. Count tokens (roughly: words * 1.3)
4. tokens / seconds = tokens/sec

Example: If response is 80 words (~100 tokens) in 5 seconds = 20 tok/s


WHAT TO LOOK FOR IN OUTPUT:
---------------------------
The demo already prints:
- "LLM Model loaded in X ms"     <- LLM load time
- "ImgEnc Model loaded in X ms"  <- Vision encoder load time

Inference timing is NOT printed by default. You'd need to modify
the source code at:
  ~/rknn-llm/examples/multimodal_model_demo/deploy/src/main.cc

EOF
