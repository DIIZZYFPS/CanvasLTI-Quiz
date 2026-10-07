# Frontend

React 19 + TypeScript + Vite + Tailwind CSS v4 (shadcn/ui primitives in `src/components/ui/`).
It is built into `../app/assets/`, which Flask serves; see the root [README](../README.md) for running the
whole app and for how the committed build works.

```bash
npm ci
npm run dev       # http://localhost:5173, proxies /api to the Flask app on :5000
npm test          # unit tests (Vitest)
npm run lint
npm run build     # type-checks, then writes ../app/assets (commit the result)
```

## Layout

```
src/
  components/
    Dashboard.tsx        page: input, quiz details, check/export flow
    PreviewDialog.tsx    question preview, error summary, export buttons
    StatusPanel.tsx      what is happening / what happened, under the Check button
    CanvasStatusPill.tsx header badge for the Canvas connection
    FileUpload.tsx       controlled file picker (state lives in Dashboard)
    FormattingGuide.tsx  the "how to format" card
    ui/                  shadcn/ui primitives
  hooks/useCanvasSession.ts   asks GET /api/session whether Canvas is connected
  lib/                   small pure helpers (quiz.ts, errors.ts, textarea.ts)
  types/quiz.ts          the shape of a parsed question (mirrors app/utils/parser.py)
```

## Things worth knowing

- **Tailwind v4 reads no `tailwind.config.ts`.** Design tokens (colours, radius, the `success`, `warning`
  and `destructive-text` shades) are CSS variables in `src/index.css`, registered with `@theme inline`.
  A class that isn't defined there generates nothing, silently; and `tailwind-merge` treats an unknown
  `bg-something` as a background colour, so it can delete a component's real `bg-primary`.
- **Tailwind finds classes by scanning source for whole strings.** Never build one by concatenation
  (`` `bg-${tone}/10` ``): the CSS is never generated. Use a literal map of full class names.
- **Canvas state comes from the server** (`/api/session`), never from the page or `sessionStorage`; the
  server session is the only thing that knows whether the Canvas token is still valid.
- **A preview is only valid for the input it was made from.** Editing the input discards it, and inputs are
  locked while a request is in flight.
- Errors from the API are `{ "error": "..." }`. Use `readApiError` (`lib/errors.ts`): downloads use
  `responseType: 'blob'`, which delivers that JSON as a Blob.
