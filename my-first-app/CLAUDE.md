# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
npm run dev      # start dev server at http://localhost:5173 with HMR
npm run build    # production build to dist/
npm run lint     # run ESLint across all .js/.jsx files
npm run preview  # preview production build locally
```

No test suite is configured yet (Vitest planned).

## Architecture

React 19 + Vite 8 SPA. Entry point is `src/main.jsx` → renders `<App />` into `#root` in `index.html`.

### Routing

`src/App.jsx` wraps everything in `<BrowserRouter>`. `<Navbar>` is rendered outside `<Routes>` so it appears on every page:

```jsx
<BrowserRouter>
  <Navbar />
  <Routes>
    <Route path="/" element={<Home />} />
    <Route path="/about" element={<About />} />
  </Routes>
</BrowserRouter>
```

### NavLink active state

`Navbar.jsx` uses `NavLink` with `className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}`. The `/` route uses the `end` prop to prevent it staying active on all sub-routes.

### Pages vs Components

- `src/pages/` — one file per route, mounted by the router
- `src/components/` — shared UI; each component has a co-located `.css` file

### Styling

Plain CSS, no CSS modules or utility frameworks. Global design tokens are CSS custom properties in `src/index.css`:

| Variable            | Purpose                                   |
| ------------------- | ----------------------------------------- |
| `--text`            | body text                                 |
| `--text-h`          | headings / high-contrast text             |
| `--bg`              | page background                           |
| `--border`          | dividers and borders                      |
| `--accent`          | primary purple highlight                  |
| `--accent-bg`       | tinted background for active/hover states |
| `--accent-border`   | border for accent elements                |
| `--shadow`          | box-shadow utility                        |
| `--sans` / `--mono` | font stacks                               |

Dark mode is handled automatically via `@media (prefers-color-scheme: dark)` in `index.css` — all variables are redefined there, so no dark-mode logic is needed in components.

`src/App.css` contains layout styles for page sections: `#center` (vertically centered flex column, `flex-grow: 1`), `#next-steps` (split bottom panel), `.ticks` (decorative corner marks), `.hero` (layered logo images).

### Assets

- `src/assets/` — imported directly into JSX; Vite processes and hashes these in production builds
- `public/icons.svg` — SVG sprite sheet; reference with `<use href="/icons.svg#icon-name">`. Available IDs: `documentation-icon`, `social-icon`, `github-icon`, `discord-icon`, `x-icon`, `bluesky-icon`
- `public/favicon.svg` — site favicon

## Code Style

- Functional components with hooks only — no class components
- Named exports preferred over default exports for components
- File naming: PascalCase for components (`MyComponent.jsx`), camelCase for utilities (`formatDate.js`)
- Component file structure: imports → component → export
- Co-locate component-specific CSS as `ComponentName.css` next to `ComponentName.jsx`
- Use destructuring for props: `function Button({ label, onClick })` not `props.label`
- Prefer early returns over nested ternaries
- 2-space indentation (enforced by ESLint config)
- Use semantic HTML (`<main>`, `<nav>`, `<article>`, `<section>`) over generic `<div>`
- Add `aria-*` attributes for accessibility on interactive elements

## State Management

- Local state: `useState` / `useReducer`
- Cross-component state: React Context (current — no library)
- If complexity grows, plan to introduce Zustand (not Redux)
- Server state: not yet implemented; use TanStack Query when adding API calls

## Import Conventions

Order imports as:

1. External packages (react, react-router-dom)
2. Internal absolute imports (if path aliases are configured)
3. Relative imports (`./`, `../`)
4. CSS imports
5. Asset imports

Example:

```jsx
import { useState } from "react";
import { NavLink } from "react-router-dom";

import { Button } from "../components/Button";
import { formatDate } from "../lib/utils";

import "./HomePage.css";
import logo from "../assets/logo.svg";
```

## Adding a New Page

1. Create `src/pages/MyPage.jsx` (PascalCase)
2. Create `src/pages/MyPage.css` if it needs custom styles
3. Add `<Route path="/my-page" element={<MyPage />} />` in `App.jsx`
4. Add `<NavLink to="/my-page">My Page</NavLink>` in `Navbar.jsx`
5. Use existing CSS variables from `index.css` — do not hardcode colors

## Adding a New Component

1. Create `src/components/MyComponent.jsx` and `MyComponent.css`
2. Use named export: `export function MyComponent() {...}`
3. Import CSS at the top of the component file
4. Document non-obvious props with JSDoc comments
5. Keep components focused — split when a file exceeds ~150 lines

## Patterns to Follow

### Page component skeleton

```jsx
import "./MyPage.css";

export function MyPage() {
  return (
    <main id="center">
      <h1>Page Title</h1>
      {/* content */}
    </main>
  );
}
```

### Component skeleton

```jsx
import "./MyComponent.css";

/**
 * Brief description of what this component does.
 */
export function MyComponent({ label, onClick }) {
  return (
    <button className="my-component" onClick={onClick}>
      {label}
    </button>
  );
}
```

### Icon usage

```jsx
<svg className="icon" aria-hidden="true">
  <use href="/icons.svg#github-icon" />
</svg>
```

### NavLink with active state

```jsx
<NavLink
  to="/path"
  end // only on root route to prevent matching sub-routes
  className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
>
  Label
</NavLink>
```

### Using CSS variables in component styles

```css
.my-component {
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border);
}

.my-component:hover {
  background: var(--accent-bg);
  border-color: var(--accent-border);
}
```

## Constraints

These are intentional design decisions — do not change without discussion:

- **Do NOT** introduce CSS-in-JS, styled-components, or Tailwind — stick with plain CSS + CSS variables
- **Do NOT** add TypeScript without discussion (project is pure JSX)
- **Do NOT** use default exports for new components
- **Do NOT** hardcode colors — always reference CSS variables (`var(--accent)`)
- **Do NOT** add dark-mode logic in components — handled globally in `index.css`
- **Do NOT** install large state management libraries (Redux, MobX) without need
- **Do NOT** add inline styles — put styles in the co-located `.css` file
- Keep dependencies minimal; prefer native browser APIs over libraries

## Git Conventions

- Branch naming: `feature/description`, `fix/description`, `refactor/description`
- Commit messages can be in Thai or English — be consistent within a feature
- Commit message format: `<verb> <what>` — e.g. "เพิ่มหน้า Profile", "แก้ NavLink active state", "refactor Navbar styles"
- Commit early and often — small atomic commits over large ones
- Do NOT commit: `node_modules/`, `dist/`, `.env*`, `.DS_Store`
- Before any large refactor or risky change, commit a checkpoint first

## Workflow Reminders for Claude

- For multi-step features, **propose a plan first** before writing code, then wait for approval
- After completing a feature, suggest a commit message based on the diff
- When uncertain about a convention, check this file first; if still unclear, ask
- After significant architecture changes, update the relevant section in this file
- Run `npm run lint` before declaring a task complete

## Project Status

Currently a starter template with Home and About pages. Foundation includes:

- Routing scaffold (React Router v6)
- Design token system (CSS variables + automatic dark mode)
- Icon sprite system (`public/icons.svg`)
- Navbar with active-link state

## Planned Next Steps

- [ ] Add Contact page
- [ ] Set up form handling (react-hook-form + zod for validation)
- [ ] Add API integration layer (likely TanStack Query)
- [ ] Configure unit tests (Vitest + React Testing Library)
- [ ] Add 404 / NotFound page
- [ ] Consider path aliases in `vite.config.js` (`@/` → `src/`)

Update this list as items are completed or new ones are identified.
