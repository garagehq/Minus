"""
Skip button detection for Minus.

Detects "Skip Ad" buttons in OCR results for automatic ad skipping.
"""

import re


def check_skip_opportunity(all_texts: list) -> tuple:
    """
    Check OCR results for skippable "Skip" button (no countdown).

    For YouTube ads:
    - "Skip" alone = skippable NOW
    - "Skip Ad" = skippable NOW
    - "Skip 5" or "Skip Ad in 5" = NOT skippable (countdown active)

    Args:
        all_texts: List of detected text strings from OCR

    Returns:
        Tuple of (is_skippable, skip_text, countdown_seconds)
        - is_skippable: True if skip button is ready to press
        - skip_text: The detected skip-related text
        - countdown_seconds: Countdown remaining (0 if skippable, >0 if countdown)
    """
    for text in all_texts:
        text_lower = text.lower().strip()

        # Check for "Skip" with countdown number
        # Patterns: "Skip 5", "Skip Ad in 5", "Skip in 5s", "Skip 10", etc.
        countdown_match = re.search(r'skip\s*(?:ad\s*)?(?:in\s*)?(\d+)\s*s?', text_lower)
        if countdown_match:
            countdown = int(countdown_match.group(1))
            return (False, text, countdown)

        # Check for standalone "Skip" or "Skip Ad" (no number = skippable)
        # Must be short text to avoid false positives like "Skip this step"
        if re.search(r'^skip\s*(?:ad|ads)?$', text_lower) and len(text_lower) <= 10:
            return (True, text, 0)

        # Also check "Skip Ad" button variant
        if text_lower in ['skip', 'skip ad', 'skip ads', 'skipad']:
            return (True, text, 0)

    return (False, None, None)
