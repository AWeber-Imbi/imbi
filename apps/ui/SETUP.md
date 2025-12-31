# Local Development Setup with API Token

## ✅ Setup Complete

The app is now configured to use a local proxy that automatically adds your `IMBI_TOKEN` to all API requests.

### How It Works

```
Browser → Vite Dev Server (localhost:3001) → Proxy → Imbi API (imbi.aweber.io)
                                              ↓
                                      Adds Private-Token header
```

## Current Configuration

- **Dev Server**: http://localhost:3001
- **API Target**: https://imbi.aweber.io
- **Authentication**: Using `$IMBI_TOKEN` environment variable
- **Proxy Status**: ✅ Token configured

## Testing

1. Open http://localhost:3001 in your browser
2. Check browser console for API logs
3. You should see:
   - `API Base URL: /api`
   - `Using proxy with token: true`
   - Requests to `/api/ui/user`, `/api/projects`, etc.

## Troubleshooting

### Token Not Working

Check the terminal output when starting the dev server:
```bash
[Vite] API token configured: true  # Should be true
```

If it shows `false`, your `IMBI_TOKEN` environment variable isn't set.

### 401 Errors

If you see authentication errors:
1. Check that your `IMBI_TOKEN` is valid and not expired
2. Generate a new token at https://imbi.aweber.io/ui/user/tokens
3. Update your environment variable and restart the dev server

### CORS Errors

The proxy should handle CORS automatically. If you still see CORS errors:
- Make sure you're accessing via `http://localhost:3001` (not a different port)
- Check that the proxy is working (look for `[Proxy]` logs in terminal)

## Proxy Logs

When the app makes API calls, you'll see logs in the terminal:
```
[Proxy] GET /api/ui/user -> /ui/user
[Proxy] GET /api/projects -> /projects
```

This confirms the proxy is:
1. Receiving requests from the frontend
2. Rewriting paths (removing `/api` prefix)
3. Forwarding to imbi.aweber.io
4. Adding your Private-Token header

## Development Workflow

1. Make changes to code
2. Vite hot-reloads automatically
3. API calls go through proxy with your token
4. No need to login or manage sessions

## Generating API Tokens

To get an API token:
1. Visit https://imbi.aweber.io
2. Log in with OAuth
3. Go to your user profile → API Tokens
4. Generate a new token
5. Copy it and set `export IMBI_TOKEN=your_token_here` in your shell
