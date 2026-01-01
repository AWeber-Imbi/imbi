# Quick Start: Testing

## Run Tests

```bash
# Run all tests once
npm test

# Run tests in watch mode (auto re-runs on changes)
npm run test:watch

# Run with interactive UI
npm run test:ui

# Generate coverage report
npm run test:coverage
```

## Current Test Suite

✅ **32 tests passing**
- 10 tests: Auth store (JWT handling, token expiry)
- 14 tests: Login form (validation, submission, error handling)
- 8 tests: OAuth buttons (rendering, interactions, states)

## Write a New Test

### 1. Create test file next to component

```bash
src/components/MyComponent.tsx
src/components/MyComponent.test.tsx  # ← Create this
```

### 2. Basic test structure

```typescript
import { render, screen } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { MyComponent } from './MyComponent'

describe('MyComponent', () => {
  it('should render button', () => {
    render(<MyComponent />)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('should handle click', async () => {
    const user = userEvent.setup()
    render(<MyComponent />)

    await user.click(screen.getByRole('button'))

    expect(screen.getByText('Clicked!')).toBeInTheDocument()
  })
})
```

### 3. Run your test

```bash
npm run test:watch -- MyComponent
```

## Common Queries

```typescript
// By role (preferred - accessible)
screen.getByRole('button', { name: /submit/i })
screen.getByRole('textbox', { name: /email/i })

// By label (forms)
screen.getByLabelText(/email address/i)

// By text
screen.getByText(/welcome/i)

// By placeholder
screen.getByPlaceholderText(/enter your email/i)
```

## User Interactions

```typescript
const user = userEvent.setup()

// Type in input
await user.type(screen.getByLabelText(/email/i), 'test@example.com')

// Click button
await user.click(screen.getByRole('button'))

// Tab to next field
await user.tab()

// Clear input
await user.clear(screen.getByLabelText(/email/i))
```

## Async Testing

```typescript
import { waitFor } from '@/test/utils'

// Wait for element to appear
await waitFor(() => {
  expect(screen.getByText('Loaded')).toBeInTheDocument()
})

// Or use findBy (combines getBy + waitFor)
const element = await screen.findByText('Loaded')
```

## Mock Functions

```typescript
const mockFn = vi.fn()

// Mock resolved value
mockFn.mockResolvedValue({ data: 'value' })

// Mock rejected value
mockFn.mockRejectedValue(new Error('failed'))

// Check if called
expect(mockFn).toHaveBeenCalled()
expect(mockFn).toHaveBeenCalledWith({ email: 'test@example.com' })
expect(mockFn).toHaveBeenCalledTimes(1)
```

## Test a Store

```typescript
import { useMyStore } from './myStore'

describe('myStore', () => {
  beforeEach(() => {
    useMyStore.getState().resetState()
  })

  it('should update value', () => {
    useMyStore.getState().setValue('new')
    expect(useMyStore.getState().value).toBe('new')
  })
})
```

## Debugging

```typescript
// Print DOM to console
screen.debug()

// Print specific element
screen.debug(screen.getByRole('button'))

// Check what queries are available
screen.logTestingPlaygroundURL()
```

## Tips

1. **Use accessible queries first**: getByRole, getByLabelText
2. **Always await user interactions**: `await user.click()`
3. **Use waitFor for async**: Don't test loading states directly
4. **Reset state between tests**: Use beforeEach
5. **Test behavior, not implementation**: Test what users see/do

## Examples from Codebase

See these files for reference:
- `src/components/auth/LocalLoginForm.test.tsx` - Form validation
- `src/components/auth/OAuthButton.test.tsx` - Button interactions
- `src/stores/authStore.test.ts` - Store testing

## Documentation

- Full guide: [src/test/README.md](src/test/README.md)
- Complete docs: [TESTING.md](TESTING.md)
