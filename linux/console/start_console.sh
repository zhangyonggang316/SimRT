#!/bin/sh
# Invoked by local tty1 login only; SSH and nested shells stay ordinary shells.
set -eu
if [ -n "${SSH_CONNECTION:-}${SSH_TTY:-}${TMUX:-}" ]; then
    exit 0
fi
if [ "$(tty 2>/dev/null || true)" != /dev/tty1 ]; then
    exit 0
fi
command -v tmux >/dev/null 2>&1 || { printf '%s\n' 'SimRT console requires tmux.' >&2; exit 1; }
console_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export SIMRT_CONSOLE_DIR="$console_dir"
session=simrt-console
if ! tmux -L simrt-console has-session -t "$session" 2>/dev/null; then
    set -- $(stty size)
    tmux -L simrt-console -f /dev/null new-session -d -s "$session" -n SimRT -x "$2" -y "$1" 'exec python3 "$SIMRT_CONSOLE_DIR/simrt_console.py"'
    tmux -L simrt-console set-option -t "$session" status off
    tmux -L simrt-console set-option -t "$session" default-terminal xterm-256color
    tmux -L simrt-console set-option -t "$session" mouse off
    tmux -L simrt-console set-option -t "$session" destroy-unattached off
    tmux -L simrt-console set-option -g escape-time 0
    tmux -L simrt-console set-window-option -t "$session" remain-on-exit on
fi
# Upgrade the former split console to a single dashboard pane.
tmux -L simrt-console kill-pane -a -t "$session:0.0"
tmux -L simrt-console set-option -g prefix None
tmux -L simrt-console unbind-key -a
tmux -L simrt-console select-pane -t "$session:0.0"
exec tmux -L simrt-console attach-session -t "$session"
