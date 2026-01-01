# Testing Documentation

## Overview

This project uses a comprehensive testing setup with Vitest, React Testing Library, and modern testing practices.

## Test Results

```
✓ src/stores/authStore.test.ts (10 tests) 4ms
✓ src/components/auth/OAuthButton.test.tsx (8 tests) 96ms
✓ src/components/auth/LocalLoginForm.test.tsx (14 tests) 715ms

Test Files: 3 passed (3)
Tests: 32 passed (32)
Duration: 1.13s
```

## Testing Stack

- **Vitest v4.0.16** - Fast unit test framework built for Vite
- **React Testing Library v16.3.1** - Component testing with user-centric queries
- **@testing-library/user-event v14.6.1** - Realistic user interaction simulation
- **@testing-library/jest-dom v6.9.1** - Custom matchers for DOM assertions
- **jsdom v27.4.0** - DOM environment for tests

## Available Commands

```bash
# Run all tests once
npm test

# Run tests in watch mode (re-runs on file changes)
npm run test:watch

# Open interactive UI for running tests
npm run test:ui

# Generate coverage report
npm run test:coverage
```

## Test Coverage

### Current Test Suite

1. **authStore.test.ts** (10 tests)
   - ✅ JWT token encoding/decoding
   - ✅ Token storage and retrieval
   - ✅ Token expiry validation (5-minute buffer)
   - ✅ Username extraction from JWT
   - ✅ Token clearing functionality

2. **LocalLoginForm.test.tsx** (14 tests)
   - ✅ Form rendering and initial state
   - ✅ Email validation with regex
   - ✅ Real-time field validation
   - ✅ Submit button enable/disable logic
   - ✅ Error display above form
   - ✅ Loading states
   - ✅ Form submission with valid data
   - ✅ Various valid email formats
   - ✅ Email trimming

3. **OAuthButton.test.tsx** (8 tests)
   - ✅ Button rendering with provider name
   - ✅ Icon rendering for different providers (Google, GitHub, OIDC)
   - ✅ Click handlers
   - ✅ Disabled state handling
   - ✅ Fallback icon for unknown providers

## Testing Patterns Established

### 1. Component Testing Pattern

```typescript
import { render, screen } from '@/test/utils'
import userEvent from '@testing-library/user-event'

describe('MyComponent', () => {
  it('should handle user interaction', async () => {
    const user = userEvent.setup()
    render(<MyComponent />)

    await user.click(screen.getByRole('button'))

    expect(screen.getByText('Result')).toBeInTheDocument()
  })
})
```

### 2. Store Testing Pattern

```typescript
import { useAuthStore } from './authStore'

describe('myStore', () => {
  beforeEach(() => {
    useAuthStore.getState().clearState()
  })

  it('should update state', () => {
    useAuthStore.getState().updateState('value')
    expect(useAuthStore.getState().value).toBe('value')
  })
})
```

### 3. Async Testing Pattern

```typescript
await waitFor(() => {
  expect(screen.getByText('Loaded')).toBeInTheDocument()
})
```

### 4. Form Validation Testing

```typescript
it('should validate email format', async () => {
  const user = userEvent.setup()
  render(<Form />)

  await user.type(screen.getByLabelText(/email/i), 'invalid')
  await user.tab()

  await waitFor(() => {
    expect(screen.getByText(/valid email/i)).toBeInTheDocument()
  })
})
```

## Key Testing Decisions

### 1. Why Vitest?
- Native Vite integration (same config, faster)
- Compatible with Jest API (easy migration)
- Built-in coverage with v8
- Watch mode with HMR support
- 10x faster than Jest for this codebase

### 2. Testing Library Approach
- Tests focus on user behavior, not implementation
- Queries prioritize accessibility (getByRole, getByLabelText)
- userEvent simulates real browser interactions
- No direct component state testing

### 3. Test Organization
- Tests co-located with source files (*.test.tsx)
- Shared utilities in src/test/
- Test setup in src/test/setup.ts
- Custom render with providers in src/test/utils.tsx

### 4. Coverage Goals
- Critical paths (auth): 90%+ coverage
- UI components: 70%+ coverage
- Utilities: 90%+ coverage
- Overall: 80%+ coverage

## Common Test Scenarios Covered

### Authentication Flow
- ✅ Token validation and expiry
- ✅ Login form validation
- ✅ Email format validation
- ✅ OAuth provider selection
- ✅ Error handling and display

### Form Behavior
- ✅ Field validation on blur
- ✅ Real-time validation feedback
- ✅ Submit button state management
- ✅ Error message display
- ✅ Loading states
- ✅ Disabled states

### User Interactions
- ✅ Button clicks
- ✅ Form input
- ✅ Navigation
- ✅ Error recovery

## Best Practices Implemented

1. **User-Centric Testing**
   - Tests verify what users see and do
   - Accessible queries (getByRole, getByLabelText)
   - Real user interactions with userEvent

2. **Isolation and Setup**
   - Each test is independent
   - beforeEach resets state
   - Mock functions cleared between tests

3. **Async Handling**
   - Proper use of waitFor for async operations
   - User interactions always awaited
   - No act() warnings

4. **Descriptive Tests**
   - Clear test names ("should validate email format")
   - Focused assertions
   - Edge cases covered

5. **Maintainability**
   - Custom render with providers
   - Shared test utilities
   - Consistent patterns across tests

## Future Testing Opportunities

### Additional Tests to Consider

1. **useAuth Hook**
   - Login/logout flow
   - Token refresh logic
   - OAuth redirect handling
   - Error handling

2. **LoginPage Integration**
   - Provider loading
   - OAuth button interactions
   - Form submission flow
   - Error display

3. **API Client**
   - Token injection
   - 401 handling
   - Token refresh interceptor
   - Error handling

4. **Protected Routes**
   - Authentication checks
   - Redirect logic
   - Return URL preservation

5. **E2E Tests** (Future)
   - Full authentication flow
   - Cross-browser testing
   - Visual regression testing

## Debugging Tests

### View DOM State
```typescript
import { screen } from '@/test/utils'
screen.debug() // Prints current DOM
```

### Run Single Test
```bash
npm test -- LocalLoginForm.test
```

### Watch Specific File
```bash
npm run test:watch -- LocalLoginForm
```

### Check Coverage
```bash
npm run test:coverage
# Opens coverage/index.html
```

## CI/CD Integration

Tests are ready for CI/CD integration:

```yaml
# Example GitHub Actions
- name: Run tests
  run: npm test

- name: Coverage
  run: npm run test:coverage
```

## Resources

- [Full Testing Guide](src/test/README.md)
- [Vitest Documentation](https://vitest.dev/)
- [React Testing Library](https://testing-library.com/react)
- [Testing Best Practices](https://kentcdodds.com/blog/common-mistakes-with-react-testing-library)
