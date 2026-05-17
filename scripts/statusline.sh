#!/usr/bin/env bash
# lstack statusline
# Must: always exit 0, always print exactly one line, complete under 100ms

INPUT=$(cat)
[ -z "$INPUT" ] && printf "lstack" && exit 0

# Parse with jq (fast) or python3 fallback (one subprocess call total)
if command -v jq >/dev/null 2>&1; then
  MODEL=$(echo "$INPUT" | jq -r '.model.display_name // "?"' 2>/dev/null)
  PCT=$(echo "$INPUT"   | jq -r '.context_window.used_percentage // 0' 2>/dev/null | cut -d. -f1)
  COST=$(echo "$INPUT"  | jq -r '.cost.total_cost_usd // 0' 2>/dev/null | awk '{printf "%.3f",$1}')
  ADD=$(echo "$INPUT"   | jq -r '.cost.total_lines_added // 0' 2>/dev/null)
  DEL=$(echo "$INPUT"   | jq -r '.cost.total_lines_removed // 0' 2>/dev/null)
else
  PARSED=$(echo "$INPUT" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  m=d.get('model',{}).get('display_name','?')
  p=int(float(d.get('context_window',{}).get('used_percentage',0)))
  c=float(d.get('cost',{}).get('total_cost_usd',0))
  a=int(d.get('cost',{}).get('total_lines_added',0))
  r=int(d.get('cost',{}).get('total_lines_removed',0))
  print(f'{m}|{p}|{c:.3f}|{a}|{r}')
except:
  print('?|0|0.000|0|0')
" 2>/dev/null || echo "?|0|0.000|0|0")
  MODEL=$(echo "$PARSED" | cut -d'|' -f1)
  PCT=$(echo "$PARSED"   | cut -d'|' -f2)
  COST=$(echo "$PARSED"  | cut -d'|' -f3)
  ADD=$(echo "$PARSED"   | cut -d'|' -f4)
  DEL=$(echo "$PARSED"   | cut -d'|' -f5)
fi

# Defaults if parsing produced empty strings
MODEL=${MODEL:-"?"}
PCT=${PCT:-0}
COST=${COST:-"0.000"}
ADD=${ADD:-0}
DEL=${DEL:-0}

# Git branch (local only, fast)
BRANCH=$(git branch --show-current 2>/dev/null || echo "")

# Context bar (10 chars)
FILLED=$(( PCT / 10 )) 2>/dev/null || FILLED=0
BAR="" i=1
while [ $i -le 10 ]; do
  if [ "$i" -le "$FILLED" ]; then BAR="${BAR}█"; else BAR="${BAR}░"; fi
  i=$((i+1))
done

# Colors — use $'...' so real ESC bytes are assigned (not literal \033 text)
if [ "$PCT" -ge 80 ] 2>/dev/null; then C=$'\033[31m'
elif [ "$PCT" -ge 60 ] 2>/dev/null; then C=$'\033[33m'
else C=$'\033[32m'; fi
B=$'\033[1m'; D=$'\033[2m'; R=$'\033[0m'

# Branch segment
[ -n "$BRANCH" ] && BS=" ${D}on${R} ${BRANCH}" || BS=""

printf "${B}%s${R}%s  ${C}%s %s%%${R}  ${D}\$%s  +%s -%s${R}\n" \
  "$MODEL" "$BS" "$BAR" "$PCT" "$COST" "$ADD" "$DEL"

exit 0
