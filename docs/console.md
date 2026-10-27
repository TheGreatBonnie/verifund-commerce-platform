# Console (Next.js)

Routes (all under the `(console)` layout with sidebar + thread drawer):

- `/` — home: live run (ConsoleShell), recent runs, registry health.
- `/runs` — run history from the buyer API.
- `/runs/[runId]` — run detail/replay: deal room + A2A wire.
- `/sellers` — registry sellers directory.
- `/settings` — console settings + reset local state.
- `/help` — usage guide and glossary.

## Development

```bash
cd apps/console
pnpm install
pnpm run dev
pnpm run test
pnpm run typecheck
pnpm run test:e2e
```

## Notes

- Runs are authoritative from the buyer REST API (`/api/runs`, `/api/runs/:id`); the
  console only adds thin proxy routes.
- No mock data ships with the console.