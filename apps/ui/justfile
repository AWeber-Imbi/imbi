# Imbi UI development commands

# List available recipes
default:
    @just --list

# Install dependencies
install:
    npm ci

# Run development server
dev: install
    npm run dev

# Run tests
test:
    npm test

# Run tests in watch mode
test-watch:
    npm run test:watch

# Run tests with coverage
test-coverage:
    npm run test:coverage

# Run TypeScript type checking and build for production
build:
    npm run build

# Preview production build
preview:
    npm run preview

# Format code with Prettier
format:
    npm run format

# Check code formatting
format-check:
    npm run format:check

# Run linter
lint:
    npm run lint

# Run all CI checks (test + build)
ci: install test build
