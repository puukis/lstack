# LStack Dashboard

Local, read-only browser dashboard for the whole lstack system.

## Structure

```
dashboard/
├─ backend/       Python HTTP API + overview builder
│  ├─ server.py   Route handler
│  ├─ overview.py LStack-wide JSON builder
│  ├─ actions.py  Action registry (V1: all disabled)
│  ├─ audit.py    Local audit log
│  ├─ security.py Localhost/origin/redaction helpers
│  ├─ schemas.py  Constants
│  └─ static_server.py  Serve frontend/dist/
│
└─ frontend/      React + TypeScript + Vite + Tailwind + shadcn/ui
   ├─ src/
   │  ├─ api/          TanStack Query hooks + types
   │  ├─ components/   Layout, cards, actions, UI primitives
   │  ├─ pages/        OverviewPage, LBrainPage, ActionsPage, AuditPage
   │  └─ lib/          Utilities
   └─ dist/            Built static assets (served by Python)
```

## Commands

```bash
lstack dashboard              # start server at http://127.0.0.1:8765
lstack dashboard --json       # print JSON overview (no server)
lstack dashboard --dev        # start API server + Vite dev server
lstack dashboard --parallel   # legacy terminal worktree monitor
lstack dashboard --port 9000  # custom port
lstack dashboard --open       # open browser on start
lstack dashboard --allow-lan  # bind to non-localhost
```

## Development

```bash
cd ~/.claude/dashboard/frontend
bun install
bun run dev          # Vite dev server at :5173, proxies /api to :8765
```

In a separate terminal:
```bash
lstack dashboard --port 8765 --no-open
```

## Build

```bash
cd ~/.claude/dashboard/frontend
bun run build        # outputs to frontend/dist/
```

Then `lstack dashboard` serves the built assets.

## V1 Guarantees

- Read-only — no mutations, no git actions, no command runner
- No cloud, no remote assets, all HTML/CSS/JS inline or bundled
- No database writes from dashboard
- Binds to 127.0.0.1 by default
- Future interactive buttons shown as disabled
