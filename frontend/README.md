# Zaimex frontend

Next.js 16 (App Router, Cache Components) + TypeScript + Tailwind v4 + TanStack Query + React Hook Form + Zod.

The browser only talks to this app's origin; `/api/v1/*` is rewritten to the FastAPI backend
(`BACKEND_URL`), so the HttpOnly session cookie is first-party. Route protection is `src/proxy.ts`
(optimistic cookie-presence redirect) plus a client guard in `src/components/layout/app-shell.tsx`
that validates the session against `GET /auth/me`.

    cp .env.example .env.local
    npm ci && npm run dev        # http://localhost:3000 (backend must be on BACKEND_URL)
    npm run typecheck && npm run lint && npm test && npm run build

## Upload size through the proxy
Next buffers proxied request bodies and silently truncates anything above `experimental.proxyClientMaxBodySize`
(default 10 MB). `next.config.ts` sets it to the larger upload limit + 2 MB (27 MB by default), and `src/proxy.ts` +
`src/lib/upload-guard.ts` answer an oversized `POST /api/v1/projects/:id/upload` with the backend's JSON 413
(`file_too_large`). If you change the backend upload limits, set the matching `NEXT_PUBLIC_MAX_*_UPLOAD_MB` values and rebuild.
Known gap: a client that declares a huge `Content-Length` but never sends the body is not answered early through Next.
