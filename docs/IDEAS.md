# Minus - Future Ideas & Use Cases

A brainstorm of potential directions for leveraging Minus's unique position as an HDMI passthrough with dual NPUs, real-time video processing, and overlay capabilities.

---

## 1. Universal Screen Control (Vision-Based Automation)

**Core Concept:** Plug Minus between ANY device with HDMI output and use USB HID to control it. The NPUs "see" the screen and can automate interactions.

### Potential Applications:
- **Phone Automation** - Connect phone via USB-C to HDMI, use USB HID gadget mode for touch/input simulation
- **Legacy Device Control** - Automate old set-top boxes, medical equipment, industrial HMIs that only have HDMI out
- **Kiosk/Signage Management** - Monitor and interact with digital signage remotely
- **Testing Automation** - Visual regression testing for any HDMI device (game consoles, embedded systems)
- **Accessibility Bot** - Automate repetitive tasks for users with motor impairments

### Technical Approach:
- USB HID gadget mode on RK3588 for mouse/keyboard/touch simulation
- VLM for understanding UI state ("I see a login screen with username field focused")
- OCR for reading text, buttons, labels
- Action planning with local or cloud LLMs
- Macro recording and playback with visual verification

### Challenges:
- Touch coordinate mapping for different devices
- Handling animations and loading states
- Error recovery when UI doesn't match expectations

---

## 2. Real-Time 3D Enhancement (Real3D Branch)

**Core Concept:** Manipulate depth perception in real-time for 3D content.

### Potential Applications:
- **Depth Adjustment** - Make 3D more or less intense based on preference
- **2D-to-3D Conversion** - Use depth estimation models to generate 3D from 2D content
- **Comfort Mode** - Reduce eye strain by limiting depth range
- **Director Mode** - Enhance or reduce depth for specific scenes
- **VR Passthrough** - Process content for VR headset consumption

### Technical Approach:
- Frame-sequential or side-by-side 3D detection
- Disparity map manipulation
- IR emitter sync for active glasses (already prototyped)
- Depth estimation models on NPU for 2D→3D

---

## 3. Accessibility Overlays

**Core Concept:** Make any content more accessible in real-time.

### Potential Applications:
- **Live Audio Descriptions** - VLM describes visual content for blind users
- **Auto-Subtitles** - Whisper-based speech-to-text overlay for any content
- **Sign Language Avatar** - Generate sign language interpretation overlay
- **Magnification Lens** - AI-powered region zoom that follows action
- **High Contrast Mode** - Real-time contrast enhancement for low vision
- **Seizure Protection** - Detect and dampen rapid flashing content
- **Colorblind Modes** - Real-time color remapping (deuteranopia, protanopia, tritanopia)

### Technical Approach:
- Whisper on NPU for speech recognition
- Text-to-speech for audio descriptions
- VLM for scene understanding
- Real-time color space transformation in MPP encoder

---

## 4. Content Intelligence & Filtering

**Core Concept:** Understand and act on content in real-time.

### Potential Applications:
- **Smart Parental Controls** - VLM-based content analysis beyond simple ratings
- **Spoiler Shield** - Blur content matching user-defined spoiler patterns
- **Trigger Warnings** - Detect and warn about specific content types
- **News Fact-Checking** - Overlay fact-check indicators on news content
- **Product Identification** - Identify products on screen, show prices/reviews
- **Celebrity/Face Recognition** - "Who is that actor?" overlay

### Technical Approach:
- VLM for scene classification
- OCR for text extraction
- Face recognition models
- Knowledge base lookups
- Configurable filter rules

---

## 5. Gaming Enhancements

**Core Concept:** AI-powered gaming overlays and assistance.

### Potential Applications:
- **Performance Overlay** - FPS counter, latency measurement (visual analysis)
- **Map/Minimap Overlay** - Persistent map overlay for games without good minimaps
- **AI Coach** - Real-time suggestions ("enemy behind you", "low on ammo")
- **Stat Tracker** - Automatic K/D tracking, session stats via OCR
- **Stream Enhancement** - Auto-generate highlights, detect exciting moments
- **Accessibility Gaming** - Voice commands to game actions via VLM understanding
- **Anti-Rage Quit** - Detect frustration patterns, suggest breaks

### Technical Approach:
- Game-specific VLM fine-tuning
- OCR for HUD elements
- Event detection and logging
- Integration with streaming software

---

## 6. Sports & Live Event Augmentation

**Core Concept:** Enhance live sports and events with AI overlays.

### Potential Applications:
- **Player Identification** - Overlay player names/stats on live sports
- **Rule Explainer** - Detect plays and explain rules for new fans
- **Fantasy Integration** - Show fantasy points in real-time
- **Betting Odds Overlay** - Live odds display (where legal)
- **Replay Analysis** - AI-powered instant replay with annotations
- **Multi-Language Commentary** - Replace audio track with translated version

### Technical Approach:
- Sports-specific object detection
- Player tracking and identification
- Integration with sports data APIs
- Audio ducking and replacement

---

## 7. Smart Home Hub

**Core Concept:** Minus as a central intelligence for home automation.

### Potential Applications:
- **Context-Aware Automation** - "Movie mode" triggers when Netflix detected
- **Unified Remote** - Control all HDMI devices from one interface
- **Presence Detection** - Camera-based room occupancy (privacy-preserving, on-device)
- **Energy Dashboard** - Overlay power consumption of connected devices
- **Intercom Overlay** - Doorbell/camera feeds as picture-in-picture
- **Calendar/Notification Hub** - Subtle overlays for appointments, deliveries

### Technical Approach:
- Home Assistant integration
- MQTT messaging
- Scene detection for automation triggers
- Multi-source video compositing

---

## 8. Educational Tools

**Core Concept:** Transform passive viewing into active learning.

### Potential Applications:
- **Vocabulary Builder** - Already implemented for Spanish during ads!
- **Subtitle Language Learning** - Dual subtitles, vocabulary highlights
- **Documentary Enhancement** - Wikipedia overlays for mentioned topics
- **Music Education** - Chord/note overlay for music content
- **Cooking Assistant** - Pause and show recipe details, substitutions
- **Exercise Form Check** - Overlay form corrections during workout videos

### Technical Approach:
- Speech recognition for trigger words
- Knowledge graph lookups
- Pose estimation for exercise
- Recipe/nutrition databases

---

## 9. Productivity & Work

**Core Concept:** Enhance work-from-home and productivity.

### Potential Applications:
- **Meeting Transcription** - Live transcription overlay during video calls
- **Action Item Extraction** - Detect and log action items from meetings
- **Presentation Coach** - Real-time feedback on presentation delivery
- **Screen Time Analytics** - Track app usage across any device
- **Focus Mode** - Blur distracting content, enforce break schedules
- **Citation Finder** - Identify claims and find supporting sources

### Technical Approach:
- Whisper for transcription
- LLM for summarization and extraction
- Screen region classification
- Timer and notification system

---

## 10. Creative Tools

**Core Concept:** Real-time creative effects and tools.

### Potential Applications:
- **Live Filters** - Instagram-style filters on any HDMI source
- **Virtual Sets** - Green screen replacement for any background
- **Style Transfer** - Real-time artistic style application
- **Retro Effects** - CRT scanlines, VHS effects, pixel art conversion
- **Censorship/Privacy** - Auto-blur faces, license plates, etc.
- **Watermarking** - Add watermarks for content protection

### Technical Approach:
- Neural style transfer on NPU
- Background segmentation
- Face detection and tracking
- Video effects pipeline

---

## 11. Health & Wellness

**Core Concept:** Monitor and protect viewer health.

### Potential Applications:
- **Blue Light Filter** - Time-based color temperature adjustment
- **Posture Reminders** - Periodic overlay reminders
- **Eye Strain Prevention** - 20-20-20 rule enforcement
- **Binge Watch Intervention** - Detect extended viewing, suggest breaks
- **Sleep Hygiene** - Gradual dimming as bedtime approaches
- **Meditation Mode** - Calming overlays, breathing guides between content

### Technical Approach:
- Time-of-day color adjustment
- Usage pattern tracking
- Overlay notification system
- Integration with health APIs

---

## 12. Security & Privacy

**Core Concept:** Protect user privacy and security.

### Potential Applications:
- **Screen Share Privacy** - Blur sensitive info during screen sharing
- **Password Masking** - Detect and mask passwords in video content
- **Phishing Detection** - Warn about suspicious URLs shown on screen
- **Content Watermarking** - Invisible watermarks for leak tracking
- **Recording Indicator** - Overlay when screen recording detected
- **HDCP Passthrough Analysis** - (Research only) Understand DRM signals

### Technical Approach:
- Sensitive data pattern recognition
- URL extraction and reputation checking
- Steganographic watermarking
- DRM signal analysis

---

## 13. Retro Gaming & Emulation

**Core Concept:** Enhance retro gaming experience.

### Potential Applications:
- **Upscaling** - AI upscaling for retro consoles (240p → 4K)
- **Scanline/CRT Filters** - Authentic retro display simulation
- **Save State Overlay** - Visual save state management
- **Achievement Overlay** - RetroAchievements integration
- **Strategy Guide Overlay** - Context-aware hints and maps
- **Input Display** - Show controller inputs on screen

### Technical Approach:
- Super-resolution models on NPU
- Shader-like effects in MPP encoder
- Game detection via VLM/OCR
- RetroAchievements API integration

---

## 14. Multi-Device Orchestration

**Core Concept:** Coordinate multiple Minus devices.

### Potential Applications:
- **Video Wall Control** - Synchronized multi-display management
- **Follow-Me TV** - Content follows you room to room
- **Distributed Processing** - Share NPU load across devices
- **Central Monitoring** - Single dashboard for multiple Minus units
- **A/B Testing** - Different overlays on different displays

### Technical Approach:
- Device discovery and pairing
- Time synchronization
- Distributed task queue
- Central management API

---

## Implementation Priority Matrix

| Idea | Complexity | Hardware Needs | Unique Value | Fun Factor |
|------|------------|----------------|--------------|------------|
| Universal Screen Control | High | USB HID | Very High | High |
| Real3D Enhancement | Medium | IR Emitter | High | High |
| Accessibility Overlays | Medium | Audio out | Very High | Medium |
| Content Filtering | Medium | None | High | Medium |
| Gaming Enhancements | Medium | None | High | Very High |
| Sports Augmentation | High | Data APIs | Medium | High |
| Smart Home Hub | Medium | IoT Integration | High | Medium |
| Educational Tools | Low | None | High | High |
| Productivity | Medium | Audio | Medium | Medium |
| Creative Tools | Medium | None | Medium | Very High |
| Health & Wellness | Low | None | Medium | Medium |
| Security & Privacy | High | None | High | Medium |
| Retro Gaming | Medium | None | High | Very High |
| Multi-Device | High | Multiple units | Medium | Medium |

---

## Next Steps

1. **Prototype USB HID** - Test gadget mode on RK3588 for input simulation
2. **Validate Real3D** - Complete IR emitter integration, test with 3D content
3. **Whisper Integration** - Add speech recognition for subtitle/transcription features
4. **Plugin Architecture** - Design extensible system for feature modules
5. **Community Input** - Share ideas and gather feedback

---

*Last updated: 2026-02-15*
