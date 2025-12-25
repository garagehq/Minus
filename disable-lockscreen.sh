#!/bin/bash
# Disable all screen lock, idle screen, and power management features
# Run this script at login to prevent any screen locking or idle behavior

export DISPLAY=:0
export XAUTHORITY=/run/user/1000/gdm/Xauthority

# Disable GNOME screensaver and lock completely
gsettings set org.gnome.desktop.screensaver lock-enabled false
gsettings set org.gnome.desktop.screensaver idle-activation-enabled false
gsettings set org.gnome.desktop.screensaver lock-delay 0
gsettings set org.gnome.desktop.session idle-delay 0

# Disable lockscreen completely
gsettings set org.gnome.desktop.lockdown disable-lock-screen true

# Disable power management
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 0
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout 0
gsettings set org.gnome.settings-daemon.plugins.power idle-dim false
gsettings set org.gnome.settings-daemon.plugins.power ambient-enabled false
gsettings set org.gnome.settings-daemon.plugins.power power-button-action 'nothing'

# Disable X11 screen blanking and DPMS completely
xset s off
xset s noblank
xset s 0 0
xset -dpms

echo "[disable-lockscreen] All idle/lock screen features disabled"
