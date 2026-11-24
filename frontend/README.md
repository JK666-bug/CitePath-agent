# CitePath Frontend

The frontend uses React, TypeScript, and Vite. It presents the course editor, PDF reader, study plan, calendar, practice, exams, and course Q&A. The application entry point is `src/main.tsx`, and `src/App.tsx` defines the authenticated page routes.

## Run and build

Start the backend and local services as documented in the [main README](../README.md#2-setup-and-launch). Run these commands from `frontend/`.

```bash
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

The development server forwards `/api` requests to `http://127.0.0.1:8000` by default. Set `CITEPATH_API_TARGET` in the terminal environment before starting Vite if the backend uses a different address.

```bash
npm run build
npm run lint
```

The build writes to `dist/`. The browser evaluation uses the development server with the backend and data services running. [API integration](BACKEND_INTEGRATION.md) · [Browser evaluation](../evaluation/README.md)

## Source layout

| Path | Responsibility |
| --- | --- |
| `src/layout/` | Application shell and sidebar navigation |
| `src/unLogin/` | Registration and sign-in |
| `src/pages/courseEditor/` and `src/pages/courses/` | Course creation, material selection, and course list |
| `src/pages/course/` | Course information, schedule review, PDF reading, Q&A, notes, and exam cases |
| `src/pages/calendar/` | Month view and daily schedule |
| `src/pages/practice/` and `src/pages/exam/` | Practice sessions, chapter exams, and reports |
| `src/shared/` | Request handling, session state, browser navigation, and shared components |
