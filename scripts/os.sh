#!/usr/bin/env bash
# Portable OS detection and utility functions sourced by hooks and scripts.

case "$(uname -s 2>/dev/null || echo unknown)" in
  Darwin) OS="macos" ;;
  Linux) OS="linux" ;;
  MSYS*|CYGWIN*|MINGW*) OS="windows" ;;
  *) OS="linux" ;;
esac

PYTHON_AVAILABLE=false
PYTHON_EXE=""
PYTHON_MODE=""
PYTHON=""

_lstack_python_valid_exe() {
  local exe="$1"
  [ -n "${exe}" ] || return 1
  "${exe}" -c 'import sys; print(sys.version_info.major)' 2>/dev/null | grep -qx '3' || return 1
  "${exe}" -c 'import json; print(json.dumps({"ok": True}))' >/dev/null 2>&1 || return 1
}

_lstack_python_valid_py_launcher() {
  command -v py >/dev/null 2>&1 || return 1
  py -3 -c 'import sys; print(sys.version_info.major)' 2>/dev/null | grep -qx '3' || return 1
  py -3 -c 'import json; print(json.dumps({"ok": True}))' >/dev/null 2>&1 || return 1
}

_lstack_set_python_exe() {
  PYTHON_AVAILABLE=true
  PYTHON_EXE="$1"
  PYTHON_MODE="exe"
  PYTHON="${PYTHON_EXE}"
}

_lstack_detect_python() {
  local exe pattern

  for exe in python3 python; do
    if command -v "${exe}" >/dev/null 2>&1 && _lstack_python_valid_exe "${exe}"; then
      _lstack_set_python_exe "$(command -v "${exe}" 2>/dev/null || printf '%s\n' "${exe}")"
      return 0
    fi
  done

  if [ "${OS}" = "windows" ] && _lstack_python_valid_py_launcher; then
    PYTHON_AVAILABLE=true
    PYTHON_MODE="py-launcher"
    PYTHON_EXE=""
    PYTHON=""
    return 0
  fi

  if [ "${LSTACK_SKIP_ABSOLUTE_PYTHON:-}" != "1" ]; then
    for pattern in \
      '/c/Python*/python.exe' \
      '/c/Users/*/AppData/Local/Programs/Python/Python*/python.exe'; do
      while IFS= read -r exe; do
        [ -n "${exe}" ] || continue
        if [ -f "${exe}" ] && _lstack_python_valid_exe "${exe}"; then
          _lstack_set_python_exe "${exe}"
          return 0
        fi
      done <<EOF
$(compgen -G "${pattern}" 2>/dev/null || true)
EOF
    done

    for exe in /usr/local/bin/python3 /usr/bin/python3; do
      if [ -f "${exe}" ] && _lstack_python_valid_exe "${exe}"; then
        _lstack_set_python_exe "${exe}"
        return 0
      fi
    done
  fi

  return 1
}

if [ "${LSTACK_FORCE_PYTHON_UNAVAILABLE:-}" != "1" ]; then
  _lstack_detect_python || true
fi

_lstack_py_launcher_path_arg() {
  local value="$1"
  case "${value}" in
    /[A-Za-z]/*)
      if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "${value}" 2>/dev/null || printf '%s\n' "${value}"
      else
        printf '%s:%s\n' "$(printf '%s' "${value}" | cut -c2 | tr '[:lower:]' '[:upper:]')" "$(printf '%s' "${value}" | cut -c3-)"
      fi
      ;;
    *) printf '%s\n' "${value}" ;;
  esac
}

run_python() {
  if [ "${PYTHON_MODE:-}" = "py-launcher" ]; then
    if [ "$#" -gt 0 ]; then
      case "$1" in
        -*) py -3 "$@" ;;
        *) local first; first="$(_lstack_py_launcher_path_arg "$1")"; shift; py -3 "${first}" "$@" ;;
      esac
    else
      py -3
    fi
  elif [ -n "${PYTHON_EXE:-}" ]; then
    "${PYTHON_EXE}" "$@"
  else
    return 127
  fi
}

python_provider_label() {
  if [ "${PYTHON_MODE:-}" = "py-launcher" ]; then
    printf '%s\n' 'py -3'
  elif [ -n "${PYTHON_EXE:-}" ]; then
    printf '%s\n' "${PYTHON_EXE}"
  else
    printf '%s\n' 'unavailable'
  fi
}

hash_string() {
  run_python -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" "$1"
}

file_mtime() {
  run_python -c "import os,sys; print(int(os.path.getmtime(sys.argv[1])))" "$1"
}

sed_inplace() {
  if [ "${OS}" = "macos" ]; then sed -i '' "$1" "$2"
  else sed -i "$1" "$2"; fi
}

iso_now() {
  run_python -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))" 2>/dev/null || date -u '+%Y-%m-%dT%H:%M:%SZ'
}

to_native_path() {
  if [ "${OS}" = "windows" ]; then
    cygpath -w "$1" 2>/dev/null || echo "$1"
  else
    echo "$1"
  fi
}

normalize_hook_path() {
  [ "${PYTHON_AVAILABLE}" = "true" ] || { printf '%s\n' "$1"; return 0; }
  run_python -c '
import os, re, sys
p = os.path.expanduser(sys.argv[1])
m = re.match(r"^([A-Za-z]):[\\/](.*)$", p)
if m:
    print(f"/{m.group(1).lower()}/{m.group(2).replace(chr(92), '/')}")
else:
    print(p.replace(chr(92), "/"))
' "$1"
}

normalize_cwd() {
  normalize_hook_path "$1"
}

path_exists() {
  [ -e "$1" ]
}

DB_PY="${HOME}/.claude/scripts/db.py"
