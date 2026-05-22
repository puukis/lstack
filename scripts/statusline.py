import sys, json, subprocess, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

def bar(pct, width=10):
    filled = int(pct / 10)
    return "█" * filled + "░" * (width - filled)

def color(pct):
    if pct >= 80: return "\033[31m"
    if pct >= 60: return "\033[33m"
    return "\033[32m"

try:
    data = json.load(sys.stdin)
except:
    print("lstack")
    sys.exit(0)

model  = (data.get("model") or {}).get("display_name") or "?"
pct    = int(float((data.get("context_window") or {}).get("used_percentage") or 0))
cost   = float((data.get("cost") or {}).get("total_cost_usd") or 0)
add    = int((data.get("cost") or {}).get("total_lines_added") or 0)
rem    = int((data.get("cost") or {}).get("total_lines_removed") or 0)
rate_pct = int(float(
    ((data.get("rate_limits") or {}).get("five_hour") or {})
    .get("used_percentage") or 0
))

try:
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        stderr=subprocess.DEVNULL, timeout=1
    ).decode().strip()
except:
    branch = ""

R  = "\033[0m"
B  = "\033[1m"
D  = "\033[2m"
C  = color(pct)

branch_seg = f" {D}on{R} {branch}" if branch else ""

rate_seg = ""
if rate_pct >= 50:
    R_color = "\033[31m" if rate_pct >= 90 else "\033[33m" if rate_pct >= 70 else "\033[36m"
    rate_seg = f"  {R_color}rate {rate_pct}%{R}"

print(
    f"{B}{model}{R}{branch_seg}  "
    f"{C}{bar(pct)} {pct}%{R}  "
    f"{D}${cost:.3f}  +{add} -{rem}{R}"
    f"{rate_seg}"
)
sys.exit(0)
