#!/bin/bash
# patch-demo-timing.sh - Patch the multimodal demo to add inference timing
# Run this on the Youyeetoo R1

set -e

# Find rknn-llm directory
RKLLM_DIR=""
for dir in "$HOME/rknn-llm" "/root/rknn-llm"; do
    if [ -d "$dir/examples/multimodal_model_demo/deploy/src" ]; then
        RKLLM_DIR="$dir"
        break
    fi
done

if [ -z "$RKLLM_DIR" ]; then
    echo "rknn-llm directory not found"
    exit 1
fi

SRC_DIR="$RKLLM_DIR/examples/multimodal_model_demo/deploy/src"
MAIN_CPP="$SRC_DIR/main.cpp"

echo "Patching $MAIN_CPP to add inference timing..."

# Backup original
cp "$MAIN_CPP" "$MAIN_CPP.bak"

# Create the patched version
cat > "$MAIN_CPP" << 'PATCHED_CODE'
// Copyright (c) 2025 by Rockchip Electronics Co., Ltd. All Rights Reserved.
// MODIFIED: Added inference timing and token counting

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <iostream>
#include <fstream>
#include <chrono>
#include <atomic>
#include <opencv2/opencv.hpp>
#include "image_enc.h"
#include "rkllm.h"

using namespace std;
LLMHandle llmHandle = nullptr;

// ADDED: Global timing variables
std::chrono::high_resolution_clock::time_point g_first_token_time;
std::chrono::high_resolution_clock::time_point g_inference_start;
std::atomic<int> g_token_count(0);
std::atomic<bool> g_first_token(true);

void exit_handler(int signal)
{
    if (llmHandle != nullptr)
    {
        {
            cout << "程序即将退出" << endl;
            LLMHandle _tmp = llmHandle;
            llmHandle = nullptr;
            rkllm_destroy(_tmp);
        }
    }
    exit(signal);
}

int callback(RKLLMResult *result, void *userdata, LLMCallState state)
{
    if (state == RKLLM_RUN_FINISH)
    {
        // ADDED: Print timing stats
        auto end_time = std::chrono::high_resolution_clock::now();
        auto total_time = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - g_inference_start);
        auto generation_time = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - g_first_token_time);
        auto ttft = std::chrono::duration_cast<std::chrono::milliseconds>(g_first_token_time - g_inference_start);

        int tokens = g_token_count.load();
        double tok_per_sec = (tokens > 1 && generation_time.count() > 0)
            ? (tokens - 1) * 1000.0 / generation_time.count()
            : 0;

        printf("\n");
        printf("─────────────────────────────────────\n");
        printf("  Tokens generated: %d\n", tokens);
        printf("  Time to first token: %ld ms\n", ttft.count());
        printf("  Total inference time: %ld ms\n", total_time.count());
        printf("  Generation speed: %.2f tokens/sec\n", tok_per_sec);
        printf("─────────────────────────────────────\n");
    }
    else if (state == RKLLM_RUN_ERROR)
    {
        printf("\\run error\n");
    }
    else if (state == RKLLM_RUN_NORMAL)
    {
        // ADDED: Track first token time
        if (g_first_token.exchange(false)) {
            g_first_token_time = std::chrono::high_resolution_clock::now();
        }
        g_token_count++;

        printf("%s", result->text);
    }
    return 0;
}

// Expand the image into a square and fill it with the specified background color
cv::Mat expand2square(const cv::Mat& img, const cv::Scalar& background_color) {
    int width = img.cols;
    int height = img.rows;

    if (width == height) {
        return img.clone();
    }

    int size = std::max(width, height);
    cv::Mat result(size, size, img.type(), background_color);

    int x_offset = (size - width) / 2;
    int y_offset = (size - height) / 2;

    cv::Rect roi(x_offset, y_offset, width, height);
    img.copyTo(result(roi));

    return result;
}

int main(int argc, char** argv)
{
    if (argc < 7) {
        std::cerr << "Usage: " << argv[0]
                << " image_path encoder_model_path llm_model_path max_new_tokens max_context_len rknn_core_num "
                << "[img_start] [img_end] [img_content]\n";
        return -1;
    }

    const char * image_path = argv[1];
    const char * encoder_model_path = argv[2];

    RKLLMParam param = rkllm_createDefaultParam();
    param.model_path = argv[3];
    param.top_k = 1;
    param.max_new_tokens = std::atoi(argv[4]);
    param.max_context_len = std::atoi(argv[5]);
    param.skip_special_token = true;
    param.extend_param.base_domain_id = 1;

    param.img_start   = "<|vision_start|>";
    param.img_end     = "<|vision_end|>";
    param.img_content = "<|image_pad|>";

    if (argc == 7) {
        std::cerr << "[Warning] Using default img_start/img_end/img_content: "
                << param.img_start << " , "
                << param.img_end << " , "
                << param.img_content
                << ". Please customize these values according to your model, "
                << "otherwise the output may be incorrect.\n";
    }

    if (argc > 7) param.img_start   = argv[7];
    if (argc > 8) param.img_end     = argv[8];
    if (argc > 9) param.img_content = argv[9];

    int ret;
    std::chrono::high_resolution_clock::time_point t_start_us = std::chrono::high_resolution_clock::now();

    ret = rkllm_init(&llmHandle, &param, callback);
    if (ret == 0){
        printf("rkllm init success\n");
    } else {
        printf("rkllm init failed\n");
        exit_handler(-1);
    }
    std::chrono::high_resolution_clock::time_point t_load_end_us = std::chrono::high_resolution_clock::now();

    auto load_time = std::chrono::duration_cast<std::chrono::microseconds>(t_load_end_us - t_start_us);
    printf("%s: LLM Model loaded in %8.2f ms\n", __func__, load_time.count() / 1000.0);

    rknn_app_context_t rknn_app_ctx;
    memset(&rknn_app_ctx, 0, sizeof(rknn_app_context_t));

    t_start_us = std::chrono::high_resolution_clock::now();

    const int core_num = atoi(argv[6]);
    ret = init_imgenc(encoder_model_path, &rknn_app_ctx, core_num);
    if (ret != 0) {
        printf("init_imgenc fail! ret=%d model_path=%s\n", ret, encoder_model_path);
        return -1;
    }
    t_load_end_us = std::chrono::high_resolution_clock::now();

    load_time = std::chrono::duration_cast<std::chrono::microseconds>(t_load_end_us - t_start_us);
    printf("%s: ImgEnc Model loaded in %8.2f ms\n", __func__, load_time.count() / 1000.0);

    // The image is read in BGR format
    cv::Mat img = cv::imread(image_path);
    cv::cvtColor(img, img, cv::COLOR_BGR2RGB);

    // Expand the image into a square and fill it with the specified background color
    cv::Scalar background_color(127.5, 127.5, 127.5);
    cv::Mat square_img = expand2square(img, background_color);

    // Resize the image
    size_t image_width = rknn_app_ctx.model_width;
    size_t image_height = rknn_app_ctx.model_height;
    cv::Mat resized_img;
    cv::Size new_size(image_width, image_height);
    cv::resize(square_img, resized_img, new_size, 0, 0, cv::INTER_LINEAR);

    // ADDED: Time image encoding
    printf("\nEncoding image...\n");
    auto img_enc_start = std::chrono::high_resolution_clock::now();

    size_t n_image_tokens = rknn_app_ctx.model_image_token;
    size_t image_embed_len = rknn_app_ctx.model_embed_size;
    int rkllm_image_embed_len = n_image_tokens * image_embed_len;
    float img_vec[rkllm_image_embed_len];
    ret = run_imgenc(&rknn_app_ctx, resized_img.data, img_vec);
    if (ret != 0) {
        printf("run_imgenc fail! ret=%d\n", ret);
    }

    auto img_enc_end = std::chrono::high_resolution_clock::now();
    auto img_enc_time = std::chrono::duration_cast<std::chrono::milliseconds>(img_enc_end - img_enc_start);
    printf("Image encoded in %ld ms (produces %zu tokens)\n", img_enc_time.count(), n_image_tokens);

    RKLLMInput rkllm_input;
    memset(&rkllm_input, 0, sizeof(RKLLMInput));

    RKLLMInferParam rkllm_infer_params;
    memset(&rkllm_infer_params, 0, sizeof(RKLLMInferParam));

    rkllm_infer_params.mode = RKLLM_INFER_GENERATE;
    rkllm_infer_params.keep_history = 0;

    vector<string> pre_input;
    pre_input.push_back("<image>What is in the image?");
    pre_input.push_back("<image>这张图片中有什么？");
    pre_input.push_back("<image>Describe this image in one sentence.");
    cout << "\n**********************可输入以下问题对应序号获取回答/或自定义输入********************\n"
         << endl;
    for (int i = 0; i < (int)pre_input.size(); i++)
    {
        cout << "[" << i << "] " << pre_input[i] << endl;
    }
    cout << "\n*************************************************************************\n"
         << endl;

    while(true) {
        std::string input_str;
        printf("\n");
        printf("user: ");
        std::getline(std::cin, input_str);
        if (input_str == "exit")
        {
            break;
        }
        if (input_str == "clear")
        {
            ret = rkllm_clear_kv_cache(llmHandle, 1, nullptr, nullptr);
            if (ret != 0)
            {
                printf("clear kv cache failed!\n");
            }
            continue;
        }
        for (int i = 0; i < (int)pre_input.size(); i++)
        {
            if (input_str == to_string(i))
            {
                input_str = pre_input[i];
                cout << input_str << endl;
            }
        }

        // ADDED: Reset timing counters
        g_token_count = 0;
        g_first_token = true;
        g_inference_start = std::chrono::high_resolution_clock::now();

        if (input_str.find("<image>") == std::string::npos)
        {
            rkllm_input.input_type = RKLLM_INPUT_PROMPT;
            rkllm_input.role = "user";
            rkllm_input.prompt_input = (char*)input_str.c_str();
        } else {
            rkllm_input.input_type = RKLLM_INPUT_MULTIMODAL;
            rkllm_input.role = "user";
            rkllm_input.multimodal_input.prompt = (char*)input_str.c_str();
            rkllm_input.multimodal_input.image_embed = img_vec;
            rkllm_input.multimodal_input.n_image_tokens = n_image_tokens;
            rkllm_input.multimodal_input.n_image = 1;
            rkllm_input.multimodal_input.image_height = image_height;
            rkllm_input.multimodal_input.image_width = image_width;
        }
        printf("robot: ");
        rkllm_run(llmHandle, &rkllm_input, &rkllm_infer_params, NULL);
    }

    ret = release_imgenc(&rknn_app_ctx);
    if (ret != 0) {
        printf("release_imgenc fail! ret=%d\n", ret);
    }
    rkllm_destroy(llmHandle);

    return 0;
}
PATCHED_CODE

echo "Patch applied!"
echo ""
echo "Now rebuild the demo:"
echo "  cd $RKLLM_DIR/examples/multimodal_model_demo/deploy"
echo "  rm -rf build install"
echo "  mkdir build && cd build"
echo "  cmake .. -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ -DCMAKE_BUILD_TYPE=Release"
echo "  make -j\$(nproc)"
echo "  make install"
echo ""
echo "Or run: bash ~/build-multimodal-demo.sh"
