# FlowForge Frontend

Next.js (App Router) + React + TypeScript + Tailwind UI for FlowForge AI.

Server state will be managed with TanStack Query (caching + status polling); the
app talks only to the backend REST API and holds no secrets client-side.

**Status:** Skeleton scaffolded in **Milestone 0.6** — a single placeholder home
page, no backend integration yet. Built out into the full page tree (dashboard,
upload, matrix, coverage, requirement detail, eval) in **Milestone 10**.
See [`../docs/SystemDesign.md`](../docs/SystemDesign.md) §8 for the target
frontend architecture.

## Stack

- **Next.js 16** (App Router) · **React 19** · **TypeScript** (strict)
- **Tailwind CSS v4** (CSS-first config via `@import "tailwindcss"` in
  `app/globals.css`; PostCSS plugin in `postcss.config.mjs` — no
  `tailwind.config.js` in v4)
- **ESLint 9** (flat config, `eslint-config-next`)

## Local development

```bash
cd frontend
npm install        # install dependencies (first time only)
npm run dev        # start the dev server at http://localhost:3000
```

Other scripts:

```bash
npm run build      # production build
npm run start      # serve the production build
npm run lint       # ESLint
npx tsc --noEmit   # TypeScript type-check
```
