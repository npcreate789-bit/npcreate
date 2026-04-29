# CLAUDE.md — NP Create Web

This file provides guidance to Claude Code when working with this repository.

## Project Overview

**NP Create** (npcreate.co.th) — เว็บไซต์บริษัทรับยิงแอด GMV Max และทำการตลาด TikTok Shop

**Goals:**
- แสดงผลงานและ case studies ของ NP Create
- เปิดให้ลูกค้าใหม่ติดต่อผ่าน Line OA
- Admin (เจ้าของคนเดียว) จัดการเนื้อหาได้ทั้งหมด

**Target audience:** เจ้าของธุรกิจที่ขายของบน TikTok Shop ต้องการเพิ่มยอดขาย

## Commands

\`\`\`bash
npm run dev      # start dev server at http://localhost:3000
npm run build    # production build
npm run start    # run production build locally
npm run lint     # run ESLint
\`\`\`

## Tech Stack

- **Framework:** Next.js 15 (App Router)
- **Language:** TypeScript (strict mode)
- **Styling:** Tailwind CSS + shadcn/ui
- **Database:** Supabase (PostgreSQL)
- **Auth:** Supabase Auth (admin only)
- **Storage:** Supabase Storage + Cloudinary (future)
- **Animation:** Framer Motion
- **Forms:** react-hook-form + zod
- **Icons:** lucide-react
- **Hosting:** Vercel (region: Singapore)
- **DNS:** Cloudflare

## Brand Identity

**Color Theme: Tech Modern**

\`\`\`
Primary:    #6366F1 (Indigo)
Accent:     #10B981 (Emerald — สื่อถึงการเติบโต)
Highlight:  #F59E0B (Amber — สำหรับตัวเลข GMV)
Dark BG:    #0F172A
Light BG:   #FFFFFF
Text Dark:  #1E293B
Text Light: #F8FAFC
\`\`\`

**Typography:**
- Heading: Plus Jakarta Sans
- Body: Inter
- Thai: Noto Sans Thai

**Tagline:** "ปั้นยอดขาย TikTok Shop ของคุณให้โต 10 เท่าด้วย GMV Max"

## Folder Structure

\`\`\`
src/
├── app/
│   ├── (public)/                # public-facing pages
│   │   ├── page.tsx             # Home
│   │   ├── portfolio/
│   │   ├── services/
│   │   ├── about/
│   │   └── contact/
│   ├── admin/                   # admin panel (auth-protected)
│   │   ├── portfolios/
│   │   ├── services/
│   │   ├── testimonials/
│   │   └── settings/
│   ├── login/
│   ├── api/
│   ├── layout.tsx
│   └── globals.css
├── components/
│   ├── ui/                      # shadcn/ui components
│   ├── public/                  # public site components
│   └── admin/                   # admin components
├── lib/
│   ├── supabase/
│   │   ├── client.ts
│   │   ├── server.ts
│   │   └── middleware.ts
│   └── utils.ts
└── types/
    └── database.ts
\`\`\`

## Code Style

- Functional components with hooks only
- **Named exports** preferred over default exports for components
- File naming: PascalCase for components, kebab-case for routes
- 2-space indentation
- Use `cn()` helper from `@/lib/utils` to merge Tailwind classes
- Server Components by default; add `"use client"` only when needed (interactivity, hooks)
- Use TypeScript strict mode — no `any` without explanation

## Patterns to Follow

### Server Component (default)
\`\`\`tsx
import { createClient } from '@/lib/supabase/server'

export default async function Page() {
  const supabase = await createClient()
  const { data } = await supabase.from('portfolios').select('*')
  return <div>{/* render data */}</div>
}
\`\`\`

### Client Component
\`\`\`tsx
"use client"

import { useState } from 'react'

export function InteractiveComponent() {
  const [count, setCount] = useState(0)
  return <button onClick={() => setCount(c => c + 1)}>{count}</button>
}
\`\`\`

### Tailwind class merging
\`\`\`tsx
import { cn } from '@/lib/utils'

<div className={cn("base classes", isActive && "active classes", className)} />
\`\`\`

## Constraints

- **Do NOT** use `any` type without strong justification
- **Do NOT** use default exports for new components
- **Do NOT** make API calls from client components when Server Components can do it
- **Do NOT** hardcode colors — use Tailwind theme tokens
- **Do NOT** put secrets in client-side code (NEXT_PUBLIC_* only for public values)
- **Do NOT** install large dependencies without discussion
- **Do NOT** modify the database schema directly — write migration SQL files

## Database Conventions

- All tables use `uuid` primary keys with `gen_random_uuid()`
- All tables have `created_at` and `updated_at` timestamptz columns
- Use `snake_case` for column names
- Add Row Level Security (RLS) policies for all tables
- Public-facing data: read-only for anon role
- Admin operations: authenticated role only

## SEO Requirements

- Every page must have proper meta tags via `generateMetadata`
- Use Thai language as primary (`lang="th"`)
- Open Graph images for social sharing
- Structured data (JSON-LD) for Organization and Services
- Canonical URLs

## Git Conventions

- Branch naming: `feature/description`, `fix/description`
- Commit messages can be Thai or English
- Format: `<verb> <what>` — e.g. "เพิ่มหน้า Portfolio", "แก้ Navbar mobile"
- Commit early and often

## Workflow Reminders for Claude

- Propose a plan first for multi-step features
- After completing a feature, suggest commit message
- Run `npm run lint` before declaring done
- Update this file after architecture changes
- Always check Server vs Client component boundaries

## Project Status

**Phase 1 (Current):** Foundation Setup
- [ ] Project initialized
- [ ] Supabase configured
- [ ] Brand theme applied
- [ ] Layout + Navbar + Footer
- [ ] Floating Line button
- [ ] Deploy to Vercel
- [ ] Domain connected

## Planned Next Steps

**Phase 2:** Public pages (Home, Portfolio, Services, About, Contact)
**Phase 3:** Admin panel + auth
**Phase 4:** SEO + Analytics
**Phase 5:** Blog + advanced features