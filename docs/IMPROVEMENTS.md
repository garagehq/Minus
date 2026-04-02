# Minus Improvement Tracker

This document tracks code quality improvements, feature enhancements, and technical debt items.

---

## High Priority (Completed)

### Code Quality
- [x] **Fix silent exception handlers** - PR #19
  - `ad_blocker.py`: 10+ bare `except: pass` blocks now log appropriately
  - `webui.py`: Fixed bare except, standardized error responses

- [x] **Standardize API response format** - PR #19
  - All error responses now use `{success: false, error: str}` format
  - ~30 endpoints updated for consistency

- [x] **Add Spanish skip detection** - PR #19
  - Added "Omitir anuncio", "Saltar anuncio" patterns
  - Added "Omitir en X" countdown detection

### Configuration
- [x] **Extract hardcoded values to config** - PR #19
  - Animation durations (`animation_start_duration`, `animation_end_duration`)
  - Health thresholds (`frame_stale_threshold`)
  - Detection thresholds (`vlm_alone_threshold`, `scene_change_threshold`, `dynamic_cooldown`)

- [x] **Environment variable support for paths** - PR #19
  - `MINUS_USTREAMER_PATH`
  - `MINUS_VLM_MODEL_DIR`
  - `MINUS_OCR_MODEL_DIR`

### Monitoring
- [x] **Improve /api/health granularity** - PR #19
  - Detailed subsystem status (video, audio, VLM, OCR, Fire TV)
  - Simple mode for uptime monitors (`?simple=1`)

---

## Medium Priority (Completed in PR #20)

### Code Quality
- [x] **Add input validation to API endpoints** - PR #20
  - Validate pause duration in `/api/pause/<minutes>`
  - Validate color settings ranges in `/api/video/color`
  - Validate trigger-block duration and source
  - Return 400 Bad Request for invalid inputs

- [x] **Add request timeout handling** - Already implemented
  - All HTTP requests have appropriate timeouts (0.5s-10s)
  - Graceful degradation on timeout

- [ ] **Improve thread safety documentation**
  - Document lock usage patterns
  - Add thread safety notes to docstrings

### Testing
- [x] **Add integration tests** - PR #20
  - Test full detection pipeline (mock OCR + VLM)
  - Test blocking mode transitions
  - Test audio mute/unmute coordination
  - Test detection history tracking

- [x] **Add edge case tests** - PR #20
  - Test with empty/None inputs
  - Test with unicode characters
  - Test config with invalid env vars
  - Test screenshot manager with missing dirs

- [ ] **Add performance tests**
  - Measure OCR latency under load
  - Measure memory usage over time
  - Detect memory leaks

### Documentation
- [x] **Add API documentation** - PR #20
  - Created docs/API.md with all endpoints
  - Added request/response schemas
  - Documented parameter ranges and errors

- [ ] **Add deployment guide**
  - Systemd service configuration
  - Environment variable reference
  - Troubleshooting guide

### Features
- [x] **Add metrics/telemetry endpoint** - PR #20
  - Prometheus-compatible `/api/metrics` endpoint
  - Video FPS, blocking state, restarts
  - Audio state, HDMI signal, time saved

- [ ] **Add configuration reload**
  - Reload config without restart
  - API endpoint for config updates

---

## Low Priority

### Code Quality
- [ ] **Refactor large functions**
  - `_ocr_detection_loop()` in minus.py (~200 lines)
  - `_vlm_detection_loop()` in minus.py (~150 lines)
  - Consider breaking into smaller methods

- [ ] **Add type hints throughout**
  - Add type hints to function signatures
  - Add return type annotations
  - Consider using dataclasses for complex returns

- [ ] **Standardize logging format**
  - Consistent log prefixes (e.g., `[OCR]`, `[VLM]`)
  - Structured logging for JSON parsing
  - Log levels review

### Testing
- [ ] **Add edge case tests**
  - Test with empty/corrupt JPEG
  - Test with very long text strings
  - Test with special characters in OCR results

- [ ] **Add stress tests**
  - Rapid blocking/unblocking cycles
  - Memory pressure scenarios
  - Concurrent API requests

### Documentation
- [ ] **Add code comments for complex logic**
  - VLM sliding window algorithm
  - Static screen suppression logic
  - Transition frame detection

- [ ] **Create architecture diagrams**
  - Data flow diagrams
  - State machine diagrams
  - Sequence diagrams for detection flow

### Features
- [ ] **Add notification webhooks**
  - Webhook on ad detected
  - Webhook on blocking state change
  - Configurable webhook URLs

- [ ] **Add detection confidence scoring**
  - Confidence levels for OCR matches
  - Confidence levels for VLM responses
  - Expose in API and logs

---

## Quick Wins (Completed)

- [x] **Spanish language support** - PR #19
- [x] **Environment variables for paths** - PR #19
- [x] **Detailed health endpoint** - PR #19

---

## Future Ideas

See [IDEAS.md](IDEAS.md) for longer-term feature ideas including:
- Universal screen control (USB HID)
- Real-time 3D enhancement
- Accessibility overlays
- Gaming enhancements
- Smart home integration

---

*Last updated: 2026-04-02*
