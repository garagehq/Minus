"""
Skip button detection for Minus.

Detects "Skip Ad" buttons in OCR results for automatic ad skipping.
"""

import re


def check_skip_opportunity(all_texts: list) -> tuple:
    """
    Check OCR results for skippable "Skip" button.

    For YouTube/Fire TV ads:
    - "Skip" alone = skippable NOW
    - "Skip Ad" = skippable NOW
    - "Skip Ad >" or "Skip >" = skippable NOW (arrow indicates ready)
    - "Skip in X" = NOT skippable (countdown active, even if X is missing from OCR)
    - "Skip 5" or "Skip Ad in 5" = NOT skippable (countdown active)

    CRITICAL: "Skip in" WITHOUT a number means OCR missed the countdown digit.
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
        text_lower = text.lower().strip()

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

    return (False, None, None)
