#!/bin/sh
# Launcher for the status line hooks — `sh statusline_hook.sh install|capture|doctor`.
#
# No single runtime is on every Claude Code machine: a Mac set up with the native
# installer has python3 (Command Line Tools) but often no node; a Windows machine
# usually has node but python3 is not a command there. Claude Code runs hook
# commands through a POSIX shell (Git Bash on Windows), so this picks whichever
# runtime exists, node first, and hands the hook's stdin straight through. Neither
# runtime → exit 0 quietly: a status line that cannot run must never become an
# error printed on every tool call. The same choice decides which renderer the
# settings entry runs (each install hook writes a command for its own runtime).
#
# macOS ships a `python3` STUB that exists even when the Command Line Tools are
# not installed; running it pops the "install developer tools?" dialog and fails.
# `xcode-select -p` (in /usr/bin, no dialog) says whether the real python3 is there.
here=${0%/*}                      # the script's own dir — parameter expansion, no external command (PATH may be bare)
case "$here" in "$0") here=. ;; esac
what=$1
case "$what" in install|capture|doctor) ;; *) exit 0 ;; esac

have_python3() {
  command -v python3 >/dev/null 2>&1 || return 1
  if [ -x /usr/bin/xcode-select ] && [ "$(command -v python3)" = /usr/bin/python3 ]; then
    /usr/bin/xcode-select -p >/dev/null 2>&1 || return 1
  fi
  return 0
}

if command -v node >/dev/null 2>&1; then
  case "$what" in
    doctor) exec node "$here/../statusline/statusline.js" --doctor ;;
    *)      exec node "$here/statusline_$what.js" ;;
  esac
elif have_python3; then
  case "$what" in
    doctor) exec python3 "$here/../statusline/statusline.py" --doctor ;;
    *)      exec python3 "$here/statusline_$what.py" ;;
  esac
fi
[ "$what" = doctor ] && echo "catalyst status line: no runtime on this machine — the line needs node (any version) or python3 with the developer tools; install one, then start a new session."
exit 0
