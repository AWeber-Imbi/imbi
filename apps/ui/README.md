# Imbi UI V2

Modern TypeScript rewrite of Imbi's operational management platform interface.

## Tech Stack

- **Framework**: React 18 with TypeScript
- **Build Tool**: Vite
- **Styling**: Tailwind CSS
- **UI Components**: shadcn/ui (Radix UI primitives)
- **State Management**: React Query for server state
- **Routing**: React Router v7
- **Icons**: Lucide React
- **Authentication**: OAuth/OIDC via backend session cookies

## Getting Started

### Prerequisites

- Node.js 18+
- npm or yarn
- Imbi backend API running

### Installation

```bash
npm install
```

### Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Edit `.env` to set:
- `VITE_API_URL`: Backend API URL (default: http://localhost:8000)

### Development

```bash
# Ensure IMBI_TOKEN is set
export IMBI_TOKEN=your_token_here

# Start dev server
npm run dev
```

Runs the app in development mode at http://localhost:3000 (or 3001 if 3000 is in use) with hot module replacement.

**See [SETUP.md](./SETUP.md) for detailed setup instructions.**

### Build

```bash
npm run build
```

Creates an optimized production build in the `dist` directory.

### Preview Production Build

```bash
npm run preview
```

## Project Structure

```
src/
├── api/              # API client and endpoint definitions
├── components/       # React components
│   └── ui/          # Reusable UI components (shadcn/ui)
├── hooks/           # Custom React hooks
├── lib/             # Utility functions
├── pages/           # Page components
├── types/           # TypeScript type definitions
├── App.tsx          # Main app component with routing
└── main.tsx         # App entry point
```

## Authentication

The app uses OAuth/OIDC authentication managed by the backend:

1. Backend handles OAuth flow at `/ui/login`
2. Backend sets session cookie on successful authentication
3. Frontend makes authenticated requests using the session cookie
4. Protected routes redirect to backend login if not authenticated

**For development setup with production API**, see [DEV_AUTH_GUIDE.md](./DEV_AUTH_GUIDE.md)

## API Integration

API calls are handled through React Query for:
- Automatic caching and revalidation
- Loading and error states
- Optimistic updates

See `src/api/endpoints.ts` for available API methods.

## Development Notes

- API requests proxy through Vite dev server to avoid CORS issues
- Session cookies are sent automatically with `withCredentials: true`
- 401 responses trigger automatic redirect to login

## TODO

- [ ] Implement Projects view
- [ ] Implement Operations Log
- [ ] Implement Deployments view
- [ ] Implement Reports
- [ ] Implement Settings
- [ ] Add real-time updates via WebSocket
- [ ] Add comprehensive error handling
- [ ] Add loading skeletons
- [ ] Add unit tests
- [ ] Add E2E tests
