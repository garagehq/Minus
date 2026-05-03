"""
Skip button detection for Minus.

Detects "Skip Ad" buttons in OCR results for automatic ad skipping.
Supports English and Spanish patterns.
"""

import re


def check_skip_opportunity(all_texts: list) -> tuple:
    """
    Check OCR results for skippable "Skip" button.

    For YouTube/Fire TV ads (English):
    - "Skip" alone = skippable NOW
    - "Skip Ad" = skippable NOW
    - "Skip Ad >" or "Skip >" = skippable NOW (arrow indicates ready)
    - "Skip in X" = NOT skippable (countdown active, even if X is missing from OCR)
    - "Skip 5" or "Skip Ad in 5" = NOT skippable (countdown active)

    Spanish equivalents:
    - "Omitir anuncio" = skippable NOW
    - "Omitir" = skippable NOW
    - "Saltar anuncio" = skippable NOW
    - "Omitir en X" = NOT skippable (countdown active)

    CRITICAL: "Skip in" or "Omitir en" WITHOUT a number means OCR missed the countdown digit.
    This is NOT skippable - treat it as countdown still active (return countdown=99).

    Args:
        all_texts: List of detected text strings from OCR

    Returns:
        Tuple of (is_skippable, skip_text, countdown_seconds)
        - is_skippable: True if skip button is ready to press
        - skip_text: The detected skip-related text
        - countdown_seconds: Countdown remaining (0 if skippable, >0 if countdown, 99 if unknown)
    """
    for text in all_texts:
        if text is None:
            continue
        text_lower = text.lower().strip()

        # === ENGLISH PATTERNS ===

        # Check for "Skip" with countdown number FIRST
        # Patterns: "Skip 5", "Skip Ad in 5", "Skip in 5s", "Skip 10", etc.
        countdown_match = re.search(r'skip\s*(?:ad\s*)?(?:in\s*)?(\d+)\s*s?', text_lower)
        if countdown_match:
            countdown = int(countdown_match.group(1))
            if countdown > 0:  # Countdown active
                return (False, text, countdown)
            # countdown == 0 means skippable
            return (True, text, 0)

        # CRITICAL FIX: "Skip in" WITHOUT a number = OCR missed the digit
        # This is NOT skippable - countdown is still active!
        # Return countdown=99 to indicate "unknown but definitely counting"
        if re.search(r'skip\s*(?:ad\s*)?in\b', text_lower) and not re.search(r'\d', text_lower):
            return (False, text, 99)  # NOT skippable - countdown active but digit missed

        # Check for standalone "Skip" or "Skip Ad" (WITHOUT "in" = skippable)
        # The word "in" indicates a countdown is active
        if re.search(r'^skip\s*(?:ad|ads)?$', text_lower) and len(text_lower) <= 10:
            return (True, text, 0)

        # "Skip Ad >" or "Skip >" with arrow = skippable (arrow means ready)
        if re.match(r'^skip\s*(?:ad\s*)?[>\u2192\u25ba→►]+\s*$', text_lower):
            return (True, text, 0)

        # Direct matches for READY skip button text (no "in" word)
        if text_lower in ['skip', 'skip ad', 'skip ads', 'skipad', 'skip>', 'skip >', 'skip ad>', 'skip ad >']:
            return (True, text, 0)

        # === SPANISH PATTERNS ===

        # Check for "Omitir" with countdown number
        # Patterns: "Omitir en 5", "Omitir anuncio en 5", "Omitir 5s", etc.
        spanish_countdown = re.search(r'omitir\s*(?:anuncio\s*)?(?:en\s*)?(\d+)\s*s?', text_lower)
        if spanish_countdown:
            countdown = int(spanish_countdown.group(1))
            if countdown > 0:
                return (False, text, countdown)
            return (True, text, 0)

        # "Omitir en" without number = countdown active but digit missed
        if re.search(r'omitir\s*(?:anuncio\s*)?en\b', text_lower) and not re.search(r'\d', text_lower):
            return (False, text, 99)

        # Standalone "Omitir" or "Omitir anuncio" = skippable NOW
        if re.search(r'^omitir\s*(?:anuncio)?$', text_lower) and len(text_lower) <= 20:
            return (True, text, 0)

        # "Saltar anuncio" = skippable NOW (alternative Spanish phrasing)
        if re.search(r'^saltar\s*(?:anuncio)?$', text_lower) and len(text_lower) <= 20:
            return (True, text, 0)

        # Direct matches for Spanish skip button text
        if text_lower in ['omitir', 'omitir anuncio', 'saltar', 'saltar anuncio']:
            return (True, text, 0)

    return (False, None, None)


# Common OCR digit misreads used by YouTube/Netflix ad timers.
_DIGIT_FIXUP = str.maketrans({
    'o': '0', 'O': '0',
    'l': '1', 'I': '1', 'i': '1',
})


def extract_ad_seconds_remaining(all_texts):
    """Extract the seconds left on the current ad from OCR text.

    Recognised formats (and their OCR-misread siblings):
      - ``Ad 0:30`` / ``Ad0:30`` / ``Ado:30`` / ``Ad0;30`` / ``Ad1:05``
      - ``0:30 | Ad`` (Hulu)
      - ``Ad 10`` / ``Ad 5`` (Netflix countdown, seconds only)

    Returns the number of seconds remaining as an int, or ``None`` if no
    timer was spotted. Caller decides what to do with it (progress bar,
    stats row, etc.). Pure function, no side effects — easy to unit test.
    """
    for text in all_texts or []:
        if not text:
            continue
        raw = str(text).strip()
        # Normalise OCR digit/separator misreads FIRST so 'Ado;30' becomes
        # 'Ad0:30' for the patterns below.
        normalized = raw.translate(_DIGIT_FIXUP).replace(';', ':').replace('.', ':')
        norm_lower = normalized.lower()
        # "Ad MM:SS" — OCR often drops the space ('Ad0:30'). Allow optional
        # whitespace AND no boundary between 'ad' and the digit. Check this
        # before standalone "Ad N" because 'Ad 0:30' would otherwise match
        # the second regex with seconds=0.
        m = re.search(r'ad\s*(\d{1,2}):(\d{2})', norm_lower)
        if m:
            mins = int(m.group(1))
            secs = int(m.group(2))
            if 0 <= mins < 60 and 0 <= secs < 60:
                return mins * 60 + secs
        # Hulu-style: "0:30 | Ad" — timestamp BEFORE the 'ad' token
        if re.search(r'\bad\b', norm_lower):
            m = re.search(r'(\d{1,2}):(\d{2})', normalized)
            if m:
                mins = int(m.group(1))
                secs = int(m.group(2))
                if 0 <= mins < 60 and 0 <= secs < 60:
                    return mins * 60 + secs
        # "Ad N" standalone countdown (Netflix etc.) — 1-3 digit seconds.
        # Reject 'Ad N:MM' here because that was caught above already; the
        # negative lookahead prevents 'Ad 0' matching when ':30' follows.
        m = re.search(r'\bad\s+(\d{1,3})\b(?!\s*:)', norm_lower)
        if m:
            val = int(m.group(1))
            if 0 <= val <= 600:
                return val
    return None
