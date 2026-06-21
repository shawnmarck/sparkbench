#!/usr/bin/env bash
# Install zsh + Powerlevel10k for sparky login users.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y zsh git curl fontconfig

ZSH_BIN="$(command -v zsh)"
grep -qF "$ZSH_BIN" /etc/shells 2>/dev/null || echo "$ZSH_BIN" >> /etc/shells

P10K_REPO="https://github.com/romkatv/powerlevel10k.git"
P10K_MEDIA="https://github.com/romkatv/powerlevel10k-media/raw/master"

setup_user() {
  local user_home="$1"
  local username="$2"
  local p10k_dir="${user_home}/.powerlevel10k"
  local font_dir="${user_home}/.local/share/fonts"

  install -d -o "$username" -g "$username" "$font_dir"

  declare -A P10K_FONTS=(
    ["MesloLGS-NF-Regular.ttf"]="MesloLGS%20NF%20Regular.ttf"
    ["MesloLGS-NF-Bold.ttf"]="MesloLGS%20NF%20Bold.ttf"
    ["MesloLGS-NF-Italic.ttf"]="MesloLGS%20NF%20Italic.ttf"
    ["MesloLGS-NF-Bold-Italic.ttf"]="MesloLGS%20NF%20Bold%20Italic.ttf"
  )
  local out_name url_name
  for out_name in "${!P10K_FONTS[@]}"; do
    url_name="${P10K_FONTS[$out_name]}"
    if [ ! -f "${font_dir}/${out_name}" ]; then
      sudo -u "$username" curl -fsSL \
        "${P10K_MEDIA}/${url_name}" \
        -o "${font_dir}/${out_name}"
    fi
  done

  sudo -u "$username" fc-cache -f "$font_dir" >/dev/null 2>&1 || true

  if [ ! -d "${p10k_dir}/.git" ]; then
    sudo -u "$username" git clone --depth=1 "$P10K_REPO" "$p10k_dir"
  else
    sudo -u "$username" git -C "$p10k_dir" pull --ff-only
  fi

  if [ ! -f "${user_home}/.zshrc" ]; then
    install -o "$username" -g "$username" -m 644 /dev/stdin "${user_home}/.zshrc" <<'EOF'
# Powerlevel10k instant prompt (must stay at top)
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# Spark zsh defaults
HISTFILE=~/.zsh_history
HISTSIZE=50000
SAVEHIST=50000
setopt appendhistory incappendhistory sharehistory hist_ignore_all_dups

autoload -Uz compinit
compinit -C

source ~/.powerlevel10k/powerlevel10k.zsh-theme

# Kitty shell integration
if [[ -n "$KITTY_INSTALLATION_DIR" ]]; then
  source "${KITTY_INSTALLATION_DIR}/shell-integration/zsh/kitty.zsh"
fi

# User-local binaries (gh, etc.)
export PATH="$HOME/.local/bin:$PATH"

# Grok CLI
export PATH="$HOME/.grok/bin:$PATH"
[[ -r "$HOME/.grok/completions/zsh/_grok" ]] && fpath=("$HOME/.grok/completions/zsh" $fpath)

# Load p10k config when present (created by `p10k configure`)
[[ -f ~/.p10k.zsh ]] && source ~/.p10k.zsh
EOF
  fi

  if [ "$(getent passwd "$username" | cut -d: -f7)" != "$ZSH_BIN" ]; then
    chsh -s "$ZSH_BIN" "$username"
  fi
}

for user_home in /home/*; do
  username="$(basename "$user_home")"
  uid="$(id -u "$username" 2>/dev/null || true)"
  [ -n "$uid" ] && [ "$uid" -ge 1000 ] || continue
  setup_user "$user_home" "$username"
done

update_kitty_font() {
  local user_home="$1"
  local username="$2"
  local kitty_conf="${user_home}/.config/kitty/kitty.conf"
  [ -f "$kitty_conf" ] || return 0
  if grep -q '^font_family ' "$kitty_conf"; then
    sed -i 's/^font_family .*/font_family MesloLGS NF/' "$kitty_conf"
  else
    sed -i '1i font_family MesloLGS NF' "$kitty_conf"
  fi
  chown "$username:$username" "$kitty_conf"
}

for user_home in /home/*; do
  username="$(basename "$user_home")"
  uid="$(id -u "$username" 2>/dev/null || true)"
  [ -n "$uid" ] && [ "$uid" -ge 1000 ] || continue
  update_kitty_font "$user_home" "$username"
done

echo "OK: zsh + Powerlevel10k installed"
echo "  zsh: $ZSH_BIN"
echo "  Next: open Kitty and run 'p10k configure' once to pick your prompt style"