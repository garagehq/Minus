"""
VLM (Vision Language Model) integration for Minus.

Uses the FastVLM-0.5B ad-classifier (iter4, native-512 vision) on the
Axera LLM 8850 NPU for ad detection.

`detect_ad()` uses **logit-based thresholding**: it runs prefill only
(no autoregressive decode), softmaxes the first-position logits over the
full vocabulary, and compares the normalized P(Yes) against
`VLMManager.AD_THRESHOLD`. This is ~33% faster than prefill+decode and
the threshold is tunable post-hoc from logged scores without re-running
inference. See /home/radxa/axera_models/LOGIT_THRESHOLD_IMPLEMENTATION.md
and BENCHMARKS.md (iter4 @ T=0.76: F1=94.72, ~441ms).

`query_image()` is unchanged — it still uses decode-based text
generation, which is correct for the open-ended autonomous-mode screen
prompt.

Model is loaded ONCE at startup and kept running for fast inference.
"""

import os
import sys

# CRITICAL: Import torch early before any logging configuration
# This avoids "Unknown level: 'WARNING'" errors in torch.fx.passes
os.environ['PYTORCH_MATCHER_LOGLEVEL'] = 'WARNING'
os.environ['TORCH_LOGS'] = '-all'
os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
try:
    import torch  # Import torch first to avoid logging conflicts
except ImportError:
    pass  # torch might not be installed, will fail later with clear message

import time
import logging
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from config import VLM_MODEL_DIR

logger = logging.getLogger('Minus.VLM')

# Model paths. Default points at the FastVLM-0.5B ad-classifier iter4
# build; override the base dir via MINUS_VLM_MODEL_DIR.
#
# Two on-disk layouts are supported transparently:
#   * 1.5B legacy : <dir>/fastvlm_ax650_context_1k_prefill_640_int4/...
#   * 0.5B iter*  : flat <dir>/{qwen2_p128_l*_together.axmodel,
#                                qwen2_post.axmodel,
#                                image_encoder_*.axmodel,
#                                model.embed_tokens.weight.npy}
# The iter* dirs ship no tokenizer/utils of their own, so those fall
# back to the canonical FastVLM-0.5B copies (tokenizer — must match the
# model's 896-dim / 24-layer config) and the patched FastVLM-1.5B utils
# (infer_func carries the max_new_tokens cap; llava_qwen is byte-identical
# to the 0.5B copy). Each is overridable via env var.
FASTVLM_MODEL_DIR = Path(VLM_MODEL_DIR)


def _resolve_existing(env_var, candidates):
    env = os.environ.get(env_var)
    if env:
        return Path(env)
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


_legacy_llm_dir = FASTVLM_MODEL_DIR / "fastvlm_ax650_context_1k_prefill_640_int4"
if _legacy_llm_dir.exists():
    # FastVLM-1.5B legacy layout
    LLM_MODEL_PATH = _legacy_llm_dir
    VISION_MODEL_PATH = LLM_MODEL_PATH / "image_encoder_512x512.axmodel"
    EMBEDS_PATH = LLM_MODEL_PATH / "model.embed_tokens.weight.npy"
    # 1.5B decoder K/V cache was compiled for seq-len 1024.
    LLM_MAX_SEQ_LEN = 1024
else:
    # Flat 0.5B ad-classifier layout (iter4 etc.)
    LLM_MODEL_PATH = FASTVLM_MODEL_DIR
    # iter4's qwen2 decoder axmodels expect a K/V cache seq-len of 1023
    # (the reference test_ad_classifier.py / threshold_sweep.py construct
    # InferManager with max_seq_len=1023). Passing 1024 makes the decode
    # path feed a (1,1024,128) K_cache into a [1,1023,128] input → shape
    # mismatch. detect_ad is prefill-only so it never hit this; query_image
    # (decode-based, autonomous mode) did.
    LLM_MAX_SEQ_LEN = 1023
    _vision_candidates = (
        sorted(FASTVLM_MODEL_DIR.glob("image_encoder_*512*.axmodel"))
        or sorted(FASTVLM_MODEL_DIR.glob("image_encoder_*.axmodel"))
    )
    VISION_MODEL_PATH = (
        _vision_candidates[0] if _vision_candidates
        else FASTVLM_MODEL_DIR / "image_encoder_512x512_iter4.axmodel"
    )
    EMBEDS_PATH = FASTVLM_MODEL_DIR / "model.embed_tokens.weight.npy"

_models_root = FASTVLM_MODEL_DIR.parent
TOKENIZER_PATH = _resolve_existing("MINUS_VLM_TOKENIZER_DIR", [
    FASTVLM_MODEL_DIR / "fastvlm_tokenizer",
    _models_root / "FastVLM-0.5B" / "fastvlm_tokenizer",
    _models_root / "FastVLM-1.5B" / "fastvlm_tokenizer",
])

# Add utils path for LlavaConfig and InferManager
UTILS_PATH = _resolve_existing("MINUS_VLM_UTILS_DIR", [
    FASTVLM_MODEL_DIR / "utils",
    _models_root / "FastVLM-1.5B" / "utils",
    _models_root / "FastVLM-0.5B" / "utils",
])


class VLMManager:
    """
    FastVLM-0.5B ad-classifier manager for ad detection on Axera LLM 8850.

    The model is loaded once at initialization and kept running.
    Uses Python axengine for inference. `detect_ad()` uses logit-based
    thresholding (prefill-only); `query_image()` uses decode.
    """

    # Ad-detection prompt. MUST match the prompt used to calibrate
    # AD_THRESHOLD (fastvlm-holdout-test/threshold_sweep.py) byte-for-byte
    # — the threshold is only valid for this exact system + user prompt.
    AD_SYSTEM_PROMPT = "You are a helpful assistant."
    AD_PROMPT = "Is this an advertisement? Answer Yes or No."
    INPUT_SIZE = 512  # Vision encoder input size
    TOKEN_LENGTH = 64  # Number of image tokens for 512x512 input

    # --- Logit-based ad classification (FastVLM-0.5B iter4) ---
    # Calibrated on the 800-image holdout (2026-05-15). At T=0.76:
    # F1=94.72, ad-recall=94.25%, non-ad-recall=95.25%, ~441ms.
    # Tunable post-hoc from logged p_yes_norm without re-running inference.
    # Override at runtime via env MINUS_VLM_AD_THRESHOLD.
    AD_THRESHOLD = float(os.environ.get('MINUS_VLM_AD_THRESHOLD', '0.76'))
    # Qwen2 tokenizer (shared by 0.5B/1.5B): "Yes","yes"," Yes"," yes"
    YES_TOKEN_IDS = [7414, 9454, 9693, 9834]
    # "No","no"," No"," no"
    NO_TOKEN_IDS = [902, 2152, 2308, 2753]

    # Timeout for response rejection (in seconds)
    # Based on benchmark: responses > 1.0s correlate with model uncertainty
    # When timeout occurs, return low confidence to avoid false positives
    RESPONSE_TIMEOUT = 1.0

    def __init__(self):
        """Initialize VLM manager."""
        self.is_ready = False
        self._lock = threading.Lock()

        # Model components
        self.config = None
        self.tokenizer = None
        self.imer = None
        self.vision_session = None
        self.embeds = None
        self.image_processor = None

        # Validate paths
        if not FASTVLM_MODEL_DIR.exists():
            logger.error(f"FastVLM model dir not found: {FASTVLM_MODEL_DIR}")
            return

        if not LLM_MODEL_PATH.exists():
            logger.error(f"Model files not found: {LLM_MODEL_PATH}")
            return

        if not VISION_MODEL_PATH.exists():
            logger.error(f"Vision encoder not found: {VISION_MODEL_PATH}")
            return

        if not EMBEDS_PATH.exists():
            logger.error(f"Embeddings not found: {EMBEDS_PATH}")
            return

        logger.info(f"VLM using FastVLM at: {FASTVLM_MODEL_DIR}")

    def load_model(self):
        """Load the model - initializes all components."""
        if self.is_ready:
            logger.info("Model already loaded")
            return True

        try:
            logger.info("Starting FastVLM model...")
            start_time = time.time()

            # Add utils path to sys.path for imports
            if str(UTILS_PATH) not in sys.path:
                sys.path.insert(0, str(UTILS_PATH))

            # Import dependencies
            try:
                from ml_dtypes import bfloat16
                import axengine as ax
                # Suppress torch/transformers logging issues before import
                os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
                os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
                os.environ['TORCH_LOGS'] = '-all'
                # Temporarily store and reset root logger to avoid conflicts
                import logging as _logging
                _root = _logging.getLogger()
                _handlers = _root.handlers[:]
                _level = _root.level
                for h in _handlers:
                    _root.removeHandler(h)
                _root.setLevel(_logging.WARNING)
                try:
                    import transformers
                    transformers.logging.set_verbosity_error()
                    from transformers import AutoTokenizer, CLIPImageProcessor
                finally:
                    # Restore original logging configuration
                    _root.setLevel(_level)
                    for h in _handlers:
                        _root.addHandler(h)
                from llava_qwen import LlavaConfig, expand2square
                from infer_func import InferManager
            except ImportError as e:
                logger.error(f"Missing dependency: {e}")
                logger.error("Make sure axengine, transformers, ml_dtypes are installed")
                return False

            # Load config and tokenizer
            logger.info("  Loading config and tokenizer...")
            self.config = LlavaConfig.from_pretrained(str(TOKENIZER_PATH))
            self.tokenizer = AutoTokenizer.from_pretrained(
                str(TOKENIZER_PATH),
                trust_remote_code=True
            )

            # Add special tokens if needed
            mm_use_im_start_end = getattr(self.config, "mm_use_im_start_end", False)
            mm_use_im_patch_token = getattr(self.config, "mm_use_im_patch_token", True)
            if mm_use_im_patch_token:
                self.tokenizer.add_tokens(["<im_patch>"], special_tokens=True)
            if mm_use_im_start_end:
                self.tokenizer.add_tokens(["<im_start>", "<im_end>"], special_tokens=True)

            # Load LLM decoder layers
            logger.info("  Loading LLM decoder layers...")
            self.imer = InferManager(
                self.config,
                str(LLM_MODEL_PATH),
                max_seq_len=LLM_MAX_SEQ_LEN
            )

            # Load vision encoder
            logger.info("  Loading vision encoder...")
            self.vision_session = ax.InferenceSession(str(VISION_MODEL_PATH))

            # Load embeddings - KEEP AS FLOAT32 per IMPLEMENTATION_GUIDE.md.
            # mmap_mode='r' avoids resident-loading the ~520MB table; np.take
            # in the prefill path copies only the rows it needs.
            logger.info("  Loading embeddings...")
            self.embeds = np.load(str(EMBEDS_PATH), mmap_mode='r')
            logger.info(f"    Loaded embeddings: {self.embeds.shape}, dtype: {self.embeds.dtype}")

            # Initialize image processor
            self.image_processor = CLIPImageProcessor(
                size={"shortest_edge": self.INPUT_SIZE},
                crop_size={"height": self.INPUT_SIZE, "width": self.INPUT_SIZE},
                image_mean=[0, 0, 0],
                image_std=[1/255, 1/255, 1/255]
            )

            load_time = time.time() - start_time
            logger.info(f"FastVLM loaded in {load_time:.1f}s")
            self.is_ready = True
            return True

        except Exception as e:
            logger.error(f"Failed to load FastVLM: {e}")
            import traceback
            tb_str = traceback.format_exc()
            logger.error(f"Traceback:\n{tb_str}")
            return False

    def _reset_kv_cache(self):
        """Reset KV cache between inferences - CRITICAL for accuracy."""
        for i in range(self.config.num_hidden_layers):
            self.imer.k_caches[i].fill(0)
            self.imer.v_caches[i].fill(0)

    def _encode_image(self, image_path):
        """Encode image using vision encoder."""
        # Import here to avoid issues at module load time
        if str(UTILS_PATH) not in sys.path:
            sys.path.insert(0, str(UTILS_PATH))
        from llava_qwen import expand2square

        image = Image.open(image_path).convert('RGB')
        # Expand to square with black background
        image = expand2square(image, tuple(int(x*255) for x in self.image_processor.image_mean))

        # Preprocess image
        input_image = self.image_processor.preprocess(image, return_tensors='pt')['pixel_values'][0]
        input_image = input_image.unsqueeze(0)
        input_image = input_image.numpy().astype(np.uint8).transpose((0, 2, 3, 1))

        # Run vision encoder. iter4 names its input "pixel_values"; the
        # 1.5B legacy encoder used "images". Read the actual name from the
        # session so this works with either model without a code change.
        try:
            vit_input_name = self.vision_session.get_inputs()[0].name
        except Exception:
            vit_input_name = "pixel_values"
        vit_output = self.vision_session.run(None, {vit_input_name: input_image})[0]
        return vit_output

    def _get_first_logits(self, token_ids, prefill_data):
        """Run prefill only and return raw first-position logits.

        Mirrors fastvlm-holdout-test/threshold_sweep.py exactly so the
        calibrated AD_THRESHOLD stays valid. ~33% faster than
        prefill+decode since autoregressive generation is skipped.
        """
        from ml_dtypes import bfloat16

        seq_len = len(token_ids)
        slice_len = 128
        slice_indices = list(range(seq_len // slice_len + 1))

        data = None
        for slice_idx in slice_indices:
            indices = np.arange(
                slice_idx * slice_len,
                (slice_idx + 1) * slice_len,
                dtype=np.uint32,
            ).reshape((1, slice_len))

            mask = np.zeros((1, slice_len, slice_len * (slice_idx + 1))) - 65536
            data = np.zeros((1, slice_len, self.config.hidden_size)).astype(bfloat16)

            for i, t in enumerate(
                range(slice_idx * slice_len, (slice_idx + 1) * slice_len)
            ):
                if t < seq_len:
                    mask[:, i, : slice_idx * slice_len + i + 1] = 0
                    data[:, i : i + 1, :] = (
                        prefill_data[t]
                        .reshape((1, 1, self.config.hidden_size))
                        .astype(bfloat16)
                    )

            remain_len = (
                seq_len - slice_idx * slice_len
                if slice_idx == slice_indices[-1]
                else slice_len
            )
            mask = mask.astype(bfloat16)

            for layer_idx in range(self.config.num_hidden_layers):
                input_feed = {
                    "K_cache": (
                        self.imer.k_caches[layer_idx][:, 0 : slice_len * slice_idx, :]
                        if slice_idx
                        else np.zeros((1, 1, self.config.hidden_size), dtype=bfloat16)
                    ),
                    "V_cache": (
                        self.imer.v_caches[layer_idx][:, 0 : slice_len * slice_idx, :]
                        if slice_idx
                        else np.zeros((1, 1, self.config.hidden_size), dtype=bfloat16)
                    ),
                    "indices": indices,
                    "input": data,
                    "mask": mask,
                }
                outputs = self.imer.decoder_sessions[layer_idx].run(
                    None, input_feed, shape_group=slice_idx + 1
                )
                self.imer.k_caches[layer_idx][
                    :, slice_idx * slice_len : slice_idx * slice_len + remain_len, :
                ] = outputs[0][:, :remain_len, :]
                self.imer.v_caches[layer_idx][
                    :, slice_idx * slice_len : slice_idx * slice_len + remain_len, :
                ] = outputs[1][:, :remain_len, :]
                data = outputs[2]

        post_out = self.imer.post_process_session.run(
            None,
            {"input": data[:, seq_len - (len(slice_indices) - 1) * slice_len - 1, None, :]},
        )[0]

        return post_out

    def _compute_ad_score(self, logits):
        """Full-vocabulary softmax → (p_yes, p_no, p_yes_norm).

        p_yes_norm is the normalized P(model predicts "Yes" / ad).
        """
        logits_flat = logits.astype(np.float32).flatten()
        shifted = logits_flat - logits_flat.max()
        exp_l = np.exp(shifted)
        probs = exp_l / exp_l.sum()

        p_yes = float(sum(probs[tid] for tid in self.YES_TOKEN_IDS))
        p_no = float(sum(probs[tid] for tid in self.NO_TOKEN_IDS))
        p_yes_norm = p_yes / (p_yes + p_no) if (p_yes + p_no) > 0 else 0.5

        return p_yes, p_no, p_yes_norm

    def query_image(self, image_path, prompt, max_new_tokens=8):
        """
        Run a custom prompt on an image.

        Args:
            image_path: Path to image file (JPEG/PNG)
            prompt: Custom question to ask about the image
            max_new_tokens: Cap on generated tokens. Default 8 fits the
                autonomous-mode multi-choice prompt (PLAYING / PAUSED /
                DIALOG / MENU / SCREENSAVER, each ~1-3 tokens). Raise
                explicitly for open-ended prompts; see
                docs/VLM_NPU_DEGRADATION.md for why a cap matters.

        Returns:
            tuple: (response_text, elapsed_time)
        """
        if not self.is_ready:
            return "VLM not ready", 0

        if not os.path.exists(image_path):
            return f"Image not found: {image_path}", 0

        from ml_dtypes import bfloat16

        with self._lock:
            try:
                start_time = time.time()
                self._reset_kv_cache()
                image_features = self._encode_image(image_path)

                # Short system prompt: the iter4 LLM is p128 (one 128-token
                # prefill chunk). The verbose system message used to push
                # this past 128 → infer_func asks axengine for a 2nd prefill
                # shape-group that a p128 model doesn't have → IndexError on
                # every call. Match detect_ad's short system for headroom.
                full_prompt = (
                    "<|im_start|>system\n" + self.AD_SYSTEM_PROMPT + "<|im_end|>\n"
                )
                full_prompt += "<|im_start|>user\n" + "<image>" * self.TOKEN_LENGTH + "\n"
                full_prompt += prompt + "<|im_end|>\n<|im_start|>assistant\n"

                token_ids = self.tokenizer.encode(full_prompt)

                # Defensive guard: the p128 model physically cannot prefill
                # >128 tokens in one chunk and has no multi-chunk shape
                # group. Rather than crash autonomous mode every cycle on a
                # too-long caller prompt, fail soft with a clear sentinel
                # (callers already treat non-category responses as "unknown
                # screen" and no-op). 128 = single p128 prefill chunk.
                if len(token_ids) > 128:
                    logger.warning(
                        f"query_image prompt is {len(token_ids)} tokens > 128 "
                        f"(p128 single-chunk limit) — shorten the prompt; "
                        f"returning PROMPT_TOO_LONG without inference"
                    )
                    return "PROMPT_TOO_LONG", time.time() - start_time

                prefill_data = np.take(self.embeds, token_ids, axis=0)
                prefill_data = prefill_data.astype(bfloat16)

                image_token_indices = np.where(np.array(token_ids) == 151646)[0]
                if len(image_token_indices) > 0:
                    image_start_index = image_token_indices[0]
                    image_insert_index = image_start_index + 1
                    prefill_data[image_insert_index:image_insert_index + self.TOKEN_LENGTH] = \
                        image_features[0, :, :].astype(bfloat16)

                eos_token_id = None
                if isinstance(self.config.eos_token_id, list) and len(self.config.eos_token_id) > 1:
                    eos_token_id = self.config.eos_token_id

                slice_len = 128
                token_ids = self.imer.prefill(
                    self.tokenizer, token_ids, prefill_data, slice_len=slice_len
                )
                response = self.imer.decode(
                    self.tokenizer, token_ids, self.embeds,
                    slice_len=slice_len, eos_token_id=eos_token_id, stream=False,
                    max_new_tokens=max_new_tokens,
                )

                elapsed = time.time() - start_time
                return response, elapsed

            except Exception as e:
                import traceback
                logger.error(f"VLM query error: {e}\n{traceback.format_exc()}")
                return str(e), time.time() - start_time

    def detect_ad(self, image_path):
        """
        Run ad detection on an image.

        Args:
            image_path: Path to image file (JPEG/PNG)

        Returns:
            tuple: (is_ad, response_text, elapsed_time, confidence)
                - is_ad: bool, whether the VLM thinks this is an ad
                - response_text: str, raw response from VLM
                - elapsed_time: float, inference time in seconds
                - confidence: float, 0.0-1.0 confidence score
        """
        if not self.is_ready:
            return False, "VLM not ready", 0, 0.0

        if not os.path.exists(image_path):
            return False, f"Image not found: {image_path}", 0, 0.0

        # Import bfloat16 here
        from ml_dtypes import bfloat16

        with self._lock:
            try:
                start_time = time.time()

                # Reset KV cache for fresh inference
                self._reset_kv_cache()

                # Encode image
                image_features = self._encode_image(image_path)

                # Build prompt EXACTLY as calibrated in threshold_sweep.py.
                # Image tokens first, then the question. The AD_THRESHOLD is
                # only valid for this byte-for-byte prompt + system message.
                full_prompt = (
                    "<|im_start|>system\n" + self.AD_SYSTEM_PROMPT + "<|im_end|>\n"
                )
                full_prompt += "<|im_start|>user\n" + "<image>" * self.TOKEN_LENGTH
                full_prompt += "\n" + self.AD_PROMPT + "<|im_end|>\n"
                full_prompt += "<|im_start|>assistant\n"

                token_ids = self.tokenizer.encode(full_prompt)

                # Prepare prefill data - use astype() NOT view() per IMPLEMENTATION_GUIDE.md
                prefill_data = np.take(self.embeds, token_ids, axis=0)
                prefill_data = prefill_data.astype(bfloat16)

                # Splice the 64 vision features over the 64 <image> token
                # embeddings. Image token ID is 151646. Insert AT the first
                # image token (no +1 offset) — mirrors threshold_sweep.py.
                image_token_indices = np.where(np.array(token_ids) == 151646)[0]
                if len(image_token_indices) > 0:
                    img_idx = int(image_token_indices[0])
                    prefill_data[img_idx:img_idx + self.TOKEN_LENGTH] = \
                        image_features[0, :, :].astype(bfloat16)

                # --- LOGIT-BASED CLASSIFICATION (prefill only, no decode) ---
                logits = self._get_first_logits(token_ids, prefill_data)
                p_yes, p_no, p_yes_norm = self._compute_ad_score(logits)

                is_ad = p_yes_norm > self.AD_THRESHOLD
                confidence = p_yes_norm if is_ad else (1.0 - p_yes_norm)
                response = f"{'Yes' if is_ad else 'No'} (p={p_yes_norm:.4f})"

                elapsed = time.time() - start_time
                logger.info(
                    f"VLM: {'AD' if is_ad else 'NO-AD'} p_yes={p_yes_norm:.4f} "
                    f"raw_yes={p_yes:.6f} raw_no={p_no:.6f} "
                    f"T={self.AD_THRESHOLD} lat={elapsed:.3f}s"
                )

                return is_ad, response, elapsed, confidence

            except Exception as e:
                logger.error(f"VLM inference error: {e}")
                import traceback
                traceback.print_exc()
                return False, str(e), time.time() - start_time, 0.0

    def _parse_confidence(self, response):
        """
        Parse confidence level from VLM response.

        Returns:
            float: Confidence score 0.0-1.0
            - 0.9-1.0: High confidence (definitely, clearly, certainly)
            - 0.6-0.8: Medium confidence (default, no qualifiers)
            - 0.3-0.5: Low confidence (maybe, possibly, might)
            - 0.1-0.2: Very low confidence (uncertain, not sure)
        """
        r = response.lower()

        # High confidence indicators
        high_conf = ['definitely', 'clearly', 'certainly', 'absolutely',
                     '100%', 'sure', 'obvious', 'without doubt', 'no doubt']
        for word in high_conf:
            if word in r:
                return 0.95

        # Low confidence indicators
        low_conf = ['maybe', 'possibly', 'might', 'could be', 'perhaps',
                    'probably', 'likely', 'appears to', 'seems to', 'looks like']
        for word in low_conf:
            if word in r:
                return 0.5

        # Very low confidence indicators
        very_low = ['not sure', 'uncertain', 'unclear', 'hard to tell',
                    'difficult to say', 'cannot determine', "can't tell"]
        for word in very_low:
            if word in r:
                return 0.3

        # Default medium confidence
        return 0.75

    def _is_ad_response(self, response):
        """
        Check if VLM response indicates an ad - STRICT parsing to reduce false positives.

        Returns:
            tuple: (is_ad: bool, confidence: float)
        """
        r = response.lower().strip()
        confidence = self._parse_confidence(response)

        # Check for explicit No first (bias toward not blocking)
        if r.startswith('no') or r == 'n':
            return False, confidence

        # Check for explicit Yes at start only
        if r.startswith('yes') or r == 'y':
            return True, confidence

        # Check first word only (stricter than first 3 words)
        first_word = r.split()[0] if r.split() else ''
        if first_word == 'no' or first_word == 'no,' or first_word == 'no.':
            return False, confidence
        if first_word == 'yes' or first_word == 'yes,' or first_word == 'yes.':
            return True, confidence

        # Check for explicit negation phrases (these indicate NOT an ad)
        non_ad_phrases = [
            'not a commercial', 'not a tv commercial', 'not an ad',
            'not an advertisement', 'not a video ad', 'no ad',
            'this is not', 'this is a menu', 'this is a home screen',
            'this appears to be a menu', 'this appears to be a home',
            'interface', 'home screen', 'menu screen', 'app interface'
        ]
        for phrase in non_ad_phrases:
            if phrase in r:
                return False, confidence

        # Only mark as ad if explicitly stated as commercial/tv ad
        ad_phrases = ['tv commercial', 'commercial break', 'video advertisement', 'this is a commercial']
        for phrase in ad_phrases:
            if phrase in r:
                return True, confidence

        # Default to NOT an ad if uncertain (conservative - avoid false positives)
        # Very low confidence for uncertain responses
        return False, 0.3

    def release(self):
        """Release resources - clean up model components and free NPU memory."""
        import gc

        with self._lock:
            # Release InferManager first (holds NPU sessions)
            if self.imer is not None:
                try:
                    # Clear KV caches
                    if hasattr(self.imer, 'k_caches'):
                        for cache in self.imer.k_caches:
                            if cache is not None:
                                cache.fill(0)
                    if hasattr(self.imer, 'v_caches'):
                        for cache in self.imer.v_caches:
                            if cache is not None:
                                cache.fill(0)
                    # Release any axengine sessions
                    if hasattr(self.imer, 'sessions'):
                        for session in self.imer.sessions:
                            if session is not None and hasattr(session, 'release'):
                                try:
                                    session.release()
                                except Exception:
                                    pass
                except Exception as e:
                    logger.debug(f"Error cleaning up InferManager: {e}")
                self.imer = None

            # Release vision encoder session
            if self.vision_session is not None:
                try:
                    if hasattr(self.vision_session, 'release'):
                        self.vision_session.release()
                except Exception as e:
                    logger.debug(f"Error releasing vision session: {e}")
                self.vision_session = None

            # Clear other components
            self.config = None
            self.tokenizer = None
            self.embeds = None
            self.image_processor = None
            self.is_ready = False

        # Force garbage collection to free memory
        gc.collect()
        logger.info("[VLM] Model unloaded and resources released")

    def start_tokenizer_service(self):
        """Compatibility method - FastVLM uses transformers tokenizer."""
        return self.load_model()
