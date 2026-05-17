#!/usr/bin/env bash
# Portable OS detection and utility functions — sourced by all hook and scripts

case "$(uname -s)" in
  Darwin)           OS="macos" ;;
  Linux)            OS="linux" ;;
  MSYS*|CYGWIN*|MINGW*) OS="windows" ;;
  *)                OS="linux" ;;  # WSL reports Linux
esac

# Detect working Python 3 (Windows has a broken python3 store stub)
PYTHON=""
for _py in python3 python \
    /c/Python3*/python.exe \
    /usr/local/bin/python3 \
    /usr/bin/python3; do
    # expand glob without error if no match
    for _expanded in ${_py}; do
        [ -f "${_expanded}" ] || command -v "${_expanded}" >/dev/null 2>&1 || continue
        _ver="$("${_expanded}" -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo '0')"
        if [ "${_ver}" = "3" ]; then PYTHON="${_expanded}"; break 2; fi
    done
done
# PYTHON may be empty if no interpreter is found; functions degrade gracefully

# Portable sha256 hash of a string
hash_string() {
  "${PYTHON}" -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" "$1"
}

# Portable file mtime (seconds since epoch)
file_mtime() {
  "${PYTHON}" -c "import os,sys; print(int(os.path.getmtime(sys.argv[1])))" "$1"
}

# Portable sed in-place: sed_inplace 's/foo/bar/' file
sed_inplace() {
  if [ "$OS" = "macos" ]; then sed -i '' "$1" "$2"
  else sed -i "$1" "$2"; fi
}

# Portable ISO 8601 UTC timestamp
iso_now() {
  "${PYTHON}" -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))"
}
