#!/usr/bin/env bash
# Replace gnome-terminal with Kitty as default terminal emulator.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y kitty

update-alternatives --set x-terminal-emulator /usr/bin/kitty

install_desktop_overrides() {
  local user_home="$1"
  local username="$2"
  local apps_dir="${user_home}/.local/share/applications"

  install -d -o "$username" -g "$username" "$apps_dir"

  install -o "$username" -g "$username" -m 644 /dev/stdin "${apps_dir}/kitty.desktop" <<'EOF'
[Desktop Entry]
Version=1.0
Type=Application
Name=Terminal
GenericName=Terminal emulator
Comment=Fast, feature-rich, GPU based terminal
Keywords=shell;prompt;command;commandline;cmd;terminal;console;cli;
TryExec=kitty
Exec=kitty
Icon=kitty
Categories=System;TerminalEmulator;
StartupNotify=true
StartupWMClass=kitty
EOF

  install -o "$username" -g "$username" -m 644 /dev/stdin "${apps_dir}/org.gnome.Terminal.desktop" <<'EOF'
[Desktop Entry]
Hidden=true
NoDisplay=true
EOF

  install -o "$username" -g "$username" -m 644 /dev/stdin "${apps_dir}/org.gnome.Terminal.Preferences.desktop" <<'EOF'
[Desktop Entry]
Hidden=true
NoDisplay=true
EOF

  sudo -u "$username" update-desktop-database "$apps_dir" 2>/dev/null || true
}

if command -v gsettings >/dev/null 2>&1; then
  for user_home in /home/*; do
    username="$(basename "$user_home")"
    uid="$(id -u "$username" 2>/dev/null || true)"
    [ -n "$uid" ] && [ "$uid" -ge 1000 ] || continue

    install_desktop_overrides "$user_home" "$username"

    sudo -u "$username" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
      gsettings set org.gnome.desktop.default-applications.terminal exec 'kitty' 2>/dev/null || true
    sudo -u "$username" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
      gsettings set org.gnome.desktop.default-applications.terminal exec-arg '' 2>/dev/null || true
  done
fi

echo "OK: Kitty installed and set as default terminal"
echo "  x-terminal-emulator -> $(readlink -f "$(which x-terminal-emulator)")"