# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Imbi UI V2 - TypeScript Rewrite

This is a complete rewrite of the Imbi UI using modern TypeScript and React.

## Commands
- Dev server: `npm run dev` (starts Vite dev server on port 3000)
- Build: `npm run build` (TypeScript compilation + production build)
- Preview: `npm run preview` (preview production build)
- Lint: `npm run lint` (ESLint with TypeScript)

## Tech Stack
- **React 18** with **TypeScript**
- **Vite** for fast development and building
- **Tailwind CSS** for styling
- **shadcn/ui** for UI components (Radix UI primitives)
- **React Query** for server state management
- **React Router v7** for routing
- **Axios** for API calls

## Code Style
- TypeScript strict mode enabled
- Functional components with hooks
- Named exports for components (not default exports)
- Use Tailwind utility classes for styling
- Use shadcn/ui components from `@/components/ui`
- 2-space indentation

## Project Structure
- `src/api/` - API client and endpoint definitions
- `src/components/` - React components
- `src/components/ui/` - Reusable UI components (shadcn/ui)
- `src/hooks/` - Custom React hooks
- `src/pages/` - Page-level components
- `src/types/` - TypeScript type definitions
- `src/lib/` - Utility functions

## Authentication
- OAuth/OIDC flow handled by backend
- Session cookie-based authentication
- Protected routes use `useAuth()` hook
- 401 responses trigger redirect to login

## API Integration
- All API calls use React Query for caching and state management
- API client in `src/api/client.ts` handles auth headers and error responses
- Endpoints defined in `src/api/endpoints.ts`
- Types defined in `src/types/index.ts`

## Adding New Components
1. Create component in appropriate directory
2. Use TypeScript for props and state
3. Import UI components from `@/components/ui`
4. Use React Query hooks for data fetching
5. Handle loading and error states

## Backend API
- OpenAPI spec available at `imbi-openapi.yaml`
- Session cookie auth (or Private-Token header)
- Base URL configured via `VITE_API_URL` env var
- OpenSearch endpoint not documented in OpenAPI spec