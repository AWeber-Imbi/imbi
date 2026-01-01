# Testing Guide for Imbi UI

This document outlines the testing patterns and conventions for the Imbi UI project.

## Technology Stack

- **Vitest**: Fast unit test framework built on Vite
- **React Testing Library**: Component testing with user-centric queries
- **jsdom**: DOM environment for tests
- **@testing-library/user-event**: Realistic user interaction simulation

## Test File Structure

```
src/
├── components/
│   ├── ComponentName.tsx
│   └── ComponentName.test.tsx
├── hooks/
│   ├── useHookName.ts
│   └── useHookName.test.ts
├── stores/
│   ├── storeName.ts
│   └── storeName.test.ts
└── test/
    ├── setup.ts          # Global test setup
    ├── utils.tsx         # Test utilities and custom render
    └── README.md         # This file
```

## Running Tests

```bash
# Run all tests
npm test

# Run tests in watch mode
npm run test:watch

# Run tests with UI
npm run test:ui

# Generate coverage report
npm run test:coverage
```

## Writing Tests

### Component Tests

Use the custom `render` function from `@/test/utils` which provides React Query and Router context:

```typescript
import { render, screen } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { MyComponent } from './MyComponent'

describe('MyComponent', () => {
  it('should render correctly', () => {
    render(<MyComponent />)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('should handle user interaction', async () => {
    const user = userEvent.setup()
    render(<MyComponent />)

    await user.click(screen.getByRole('button'))

    expect(screen.getByText('Clicked!')).toBeInTheDocument()
  })
})
```

### Store Tests

Test Zustand stores by accessing state directly:

```typescript
import { useAuthStore } from './authStore'

describe('authStore', () => {
  beforeEach(() => {
    useAuthStore.getState().clearTokens()
  })

  it('should update state', () => {
    useAuthStore.getState().setAccessToken('token')
    expect(useAuthStore.getState().accessToken).toBe('token')
  })
})
```

### Hook Tests

Test hooks that don't use React Query directly:

```typescript
import { renderHook, act } from '@testing-library/react'
import { useMyHook } from './useMyHook'

describe('useMyHook', () => {
  it('should return correct value', () => {
    const { result } = renderHook(() => useMyHook())
    expect(result.current.value).toBe('expected')
  })
})
```

For hooks using React Query, use the `AllTheProviders` wrapper:

```typescript
import { renderHook } from '@testing-library/react'
import { AllTheProviders } from '@/test/utils'
import { useAuth } from './useAuth'

describe('useAuth', () => {
  it('should fetch user', async () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: AllTheProviders,
    })

    // Test implementation
  })
})
```

## Testing Patterns

### 1. Arrange-Act-Assert

```typescript
it('should do something', async () => {
  // Arrange: Set up test data and render
  const user = userEvent.setup()
  render(<Component />)

  // Act: Perform user actions
  await user.click(screen.getByRole('button'))

  // Assert: Verify expected outcome
  expect(screen.getByText('Result')).toBeInTheDocument()
})
```

### 2. Query Priorities

Use queries in this order of preference:

1. **Accessible queries** (preferred):
   - `getByRole`
   - `getByLabelText`
   - `getByPlaceholderText`
   - `getByText`

2. **Semantic queries**:
   - `getByAltText`
   - `getByTitle`

3. **Test IDs** (last resort):
   - `getByTestId`

### 3. Async Testing

Always use `waitFor` for asynchronous assertions:

```typescript
await waitFor(() => {
  expect(screen.getByText('Loaded')).toBeInTheDocument()
})
```

### 4. User Interactions

Always use `userEvent` for realistic interactions:

```typescript
const user = userEvent.setup()
await user.type(input, 'text')
await user.click(button)
await user.tab()
```

### 5. Mock Functions

Use Vitest's `vi.fn()` for mocks:

```typescript
const mockFn = vi.fn()
mockFn.mockResolvedValue({ data: 'value' })
mockFn.mockRejectedValue(new Error('failed'))
```

## Best Practices

1. **Test user behavior, not implementation**
   - Focus on what users see and do
   - Avoid testing internal state directly

2. **Use descriptive test names**
   - Write test names as sentences
   - Use "should" statements: `it('should validate email format')`

3. **One assertion per test** (when possible)
   - Tests should be focused and atomic
   - Use multiple assertions only when testing related behavior

4. **Clean up between tests**
   - Use `beforeEach` to reset state
   - Use `afterEach` for cleanup if needed

5. **Avoid testing implementation details**
   - Don't test CSS classes unless they affect behavior
   - Don't test component structure

6. **Test edge cases**
   - Empty states
   - Error states
   - Loading states
   - Invalid input

7. **Keep tests maintainable**
   - Extract common setup into helpers
   - Use constants for repeated test data
   - Keep tests DRY (Don't Repeat Yourself)

## Coverage Goals

- **Overall**: 80% minimum
- **Critical paths**: 90%+ (authentication, data mutations)
- **UI components**: 70%+ (focus on user interactions)
- **Utilities/helpers**: 90%+

## Common Patterns

### Testing Forms

```typescript
it('should submit form with valid data', async () => {
  const user = userEvent.setup()
  const mockSubmit = vi.fn()

  render(<Form onSubmit={mockSubmit} />)

  await user.type(screen.getByLabelText(/email/i), 'test@example.com')
  await user.type(screen.getByLabelText(/password/i), 'password')
  await user.click(screen.getByRole('button', { name: /submit/i }))

  await waitFor(() => {
    expect(mockSubmit).toHaveBeenCalledWith({
      email: 'test@example.com',
      password: 'password',
    })
  })
})
```

### Testing Error States

```typescript
it('should display error message', () => {
  render(<Component error="Something went wrong" />)
  expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
})
```

### Testing Loading States

```typescript
it('should show loading indicator', () => {
  render(<Component isLoading={true} />)
  expect(screen.getByText(/loading/i)).toBeInTheDocument()
})
```

### Testing Navigation

```typescript
it('should navigate on button click', async () => {
  const user = userEvent.setup()
  render(<Component />)

  await user.click(screen.getByRole('button', { name: /go to page/i }))

  expect(window.location.pathname).toBe('/expected-path')
})
```

## Troubleshooting

### Test fails intermittently
- Add `waitFor` for async operations
- Check for race conditions
- Ensure proper cleanup between tests

### "Not wrapped in act()" warning
- Use `userEvent` instead of `fireEvent`
- Wrap state updates in `act()`
- Use `waitFor` for async assertions

### Query not found
- Check if element is conditionally rendered
- Verify element is in the document: `screen.debug()`
- Use `findBy` for async elements

### Mock not working
- Clear mocks in `beforeEach`
- Check mock is imported before the code that uses it
- Verify mock return values are correct

## Resources

- [Vitest Documentation](https://vitest.dev/)
- [React Testing Library](https://testing-library.com/react)
- [Testing Library Queries](https://testing-library.com/docs/queries/about)
- [Common Testing Mistakes](https://kentcdodds.com/blog/common-mistakes-with-react-testing-library)
