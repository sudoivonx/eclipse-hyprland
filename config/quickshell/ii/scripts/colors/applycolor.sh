#!/usr/bin/env bash

QUICKSHELL_CONFIG_NAME="ii"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
CONFIG_DIR="$XDG_CONFIG_HOME/quickshell/$QUICKSHELL_CONFIG_NAME"
CACHE_DIR="$XDG_CACHE_HOME/quickshell"
STATE_DIR="$XDG_STATE_HOME/quickshell"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

term_alpha=100 #Set this to < 100 make all your terminals transparent
# sleep 0 # idk i wanted some delay or colors dont get applied properly
if [ ! -d "$STATE_DIR"/user/generated ]; then
  mkdir -p "$STATE_DIR"/user/generated
fi
cd "$CONFIG_DIR" || exit

colornames=''
colorstrings=''
colorlist=()
colorvalues=()

colornames=$(cat $STATE_DIR/user/generated/material_colors.scss | cut -d: -f1)
colorstrings=$(cat $STATE_DIR/user/generated/material_colors.scss | cut -d: -f2 | cut -d ' ' -f2 | cut -d ";" -f1)
IFS=$'\n'
colorlist=($colornames)     # Array of color names
colorvalues=($colorstrings) # Array of color values

apply_kitty() {
  local template="$SCRIPT_DIR/terminal/kitty-theme.conf"
  local output="$STATE_DIR/user/generated/terminal/kitty-theme.conf"
  local generated_dir="${output%/*}"
  local temp_file pid
  if [ ! -f "$template" ]; then
    echo "Template file not found for Kitty theme. Skipping that."
    return
  fi
  mkdir -p "$generated_dir"
  temp_file=$(mktemp "$generated_dir/.kitty-theme.XXXXXX") || return
  if ! cp "$template" "$temp_file"; then
    rm -f "$temp_file"
    return
  fi
  for i in "${!colorlist[@]}"; do
    sed -i "s/${colorlist[$i]} #/${colorvalues[$i]#\#}/g" "$temp_file"
  done

  if [[ -f "$output" ]] && cmp -s "$temp_file" "$output"; then
    rm -f "$temp_file"
    echo "Pulsar terminal: Kitty theme unchanged; reload skipped."
    return
  fi
  mv -f "$temp_file" "$output"
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && kill -SIGUSR1 "$pid" 2>/dev/null || true
  done < <(pgrep -x kitty || true)
}

apply_anyterm() {
  local template="$SCRIPT_DIR/terminal/sequences.txt"
  local output="$STATE_DIR/user/generated/terminal/sequences.txt"
  local generated_dir="${output%/*}"
  local temp_file
  if [ ! -f "$template" ]; then
    echo "Template file not found for Terminal. Skipping that."
    return
  fi
  mkdir -p "$generated_dir"
  temp_file=$(mktemp "$generated_dir/.sequences.XXXXXX") || return
  if ! cp "$template" "$temp_file"; then
    rm -f "$temp_file"
    return
  fi
  for i in "${!colorlist[@]}"; do
    sed -i "s/${colorlist[$i]} #/${colorvalues[$i]#\#}/g" "$temp_file"
  done
  sed -i "s/\$alpha/$term_alpha/g" "$temp_file"

  if [[ -f "$output" ]] && cmp -s "$temp_file" "$output"; then
    rm -f "$temp_file"
    echo "Pulsar terminal: OSC palette file unchanged; refreshing active terminals."
  else
    mv -f "$temp_file" "$output"
  fi

  # Keep broadcasting the active palette: newly opened terminals may not have
  # received the previous OSC sequence even when the generated file is unchanged.
  for file in /dev/pts/*; do
    if [[ $file =~ ^/dev/pts/[0-9]+$ ]]; then
      {
        cat "$output" > "$file"
      } & disown || true
    fi
  done
}

apply_term() {
  apply_anyterm &
  apply_kitty &
}

# Check if terminal theming is enabled in config
CONFIG_FILE="$XDG_CONFIG_HOME/illogical-impulse/config.json"
if [ -f "$CONFIG_FILE" ]; then
  enable_terminal=$(jq -r '.appearance.wallpaperTheming.enableTerminal' "$CONFIG_FILE")
  if [ "$enable_terminal" = "true" ]; then
    apply_term &
  fi
else
  echo "Config file not found at $CONFIG_FILE. Applying terminal theming by default."
  apply_term &
fi

# apply_qt & # Qt theming is already handled by kde-material-colors
