"""
Console blanking utilities for Minus.

Hides dmesg/login screen before GStreamer takes over the display,
ensuring the user never sees the underlying Linux console during
startup or transitions.
"""

import os
import subprocess


def blank_console():
    """Blank the console/VT to hide dmesg and login prompts.

    This ensures the user never sees the underlying Linux console during
    startup or transitions. The GStreamer kmssink will take over the display.
    """
    try:
        # Clear the current terminal
        os.system('clear')

        # Suppress kernel messages from appearing on console (only critical errors)
        # This prevents dmesg from cluttering the screen
        subprocess.run(['dmesg', '-n', '1'], capture_output=True)

        # Blank VT1 (main console) - write escape codes to clear and hide cursor
        # \033[2J = clear screen, \033[H = cursor home, \033[?25l = hide cursor
        try:
            with open('/dev/tty1', 'w') as tty:
                tty.write('\033[2J\033[H\033[?25l')
                tty.flush()
        except (PermissionError, FileNotFoundError):
            # Try with subprocess if direct write fails
            subprocess.run(
                ['sh', '-c', 'echo -e "\\033[2J\\033[H\\033[?25l" > /dev/tty1'],
                capture_output=True
            )

        # Set console to black background using setterm
        subprocess.run(
            ['setterm', '--blank', 'force', '--term', 'linux'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    except Exception:
        pass  # Best effort - don't fail startup if blanking fails


def restore_console():
    """Restore console settings on exit."""
    try:
        # Restore kernel log level to default
        subprocess.run(['dmesg', '-n', '7'], capture_output=True)

        # Show cursor and unblank
        try:
            with open('/dev/tty1', 'w') as tty:
                tty.write('\033[?25h')  # Show cursor
                tty.flush()
        except (PermissionError, FileNotFoundError):
            pass

        # Unblank console
        subprocess.run(
            ['setterm', '--blank', 'poke', '--term', 'linux'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    except Exception:
        pass
