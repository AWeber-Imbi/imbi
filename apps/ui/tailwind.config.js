/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}',
  ],
  darkMode: ['class'],
  plugins: [require('tailwindcss-animate')],
  prefix: '',
  theme: {
    container: {
      center: true,
      padding: '20px',
    },
    extend: {
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
      // Separate bg/text/border color mappings for clean utility names
      // bg-primary, bg-secondary, bg-tertiary, etc.
      backgroundColor: {
        accent: 'var(--color-background-accent)',
        action: 'var(--color-action-bg)',
        'action-hover': 'var(--color-action-bg-hover)',
        danger: 'var(--color-background-danger)',
        info: 'var(--color-background-info)',
        primary: 'var(--color-background-primary)',
        secondary: 'var(--color-background-secondary)',
        success: 'var(--color-background-success)',
        tertiary: 'var(--color-background-tertiary)',
        warning: 'var(--color-background-warning)',
      },
      // border-primary, border-secondary, border-tertiary, etc.
      borderColor: {
        accent: 'var(--color-border-accent)',
        action: 'var(--color-action-bg)',
        danger: 'var(--color-border-danger)',
        info: 'var(--color-border-info)',
        primary: 'var(--color-border-primary)',
        secondary: 'var(--color-border-secondary)',
        success: 'var(--color-border-success)',
        tertiary: 'var(--color-border-tertiary)',
        warning: 'var(--color-border-warning)',
      },
      borderRadius: {
        DEFAULT: '4px',
        full: '9999px',
        lg: 'var(--border-radius-lg)',
        md: 'var(--border-radius-md)',
        none: '0',
        sm: '4px',
      },
      borderWidth: {
        0: '0',
        2: '2px',
        DEFAULT: '0.5px',
      },
      colors: {
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        // WorkerBee amber brand palette (hardcoded per design system)
        amber: {
          bg: '#faeeda',
          border: '#ef9f27',
          'border-strong': '#854f0b',
          text: '#7c5900',
          'text-mid': '#ba7517',
        },
        // Avatar fallback
        'avatar-default': {
          bg: '#f1efe8',
          text: '#5f5e5a',
        },
        // shadcn/ui compatibility (used by button, badge, dialog, dropdown, popover, etc.)
        background: 'hsl(var(--background))',
        border: 'hsl(var(--border))',
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        foreground: 'hsl(var(--foreground))',
        input: 'hsl(var(--input))',
        'link-blocks': {
          bg: '#fcebeb',
          text: '#a32d2d',
        },
        'link-followup': {
          bg: '#eeedfe',
          text: '#3c3489',
        },
        // Link type colors
        'link-related': {
          bg: '#e6f1fb',
          text: '#185fa5',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        ring: 'hsl(var(--ring))',
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        'status-failed': {
          bg: '#fcebeb',
          dot: '#e24b4a',
          text: '#791f1f',
        },
        'status-feedback': {
          bg: '#faeeda',
          dot: '#ef9f27',
          text: '#7c5900',
        },
        'status-implementing': {
          bg: '#eeedfe',
          dot: '#7f77dd',
          text: '#3c3489',
        },
        // Task status colors
        'status-queued': {
          bg: '#f1efe8',
          dot: '#888780',
          text: '#444441',
        },
        'status-review': {
          bg: '#eaf3de',
          dot: '#639922',
          text: '#27500a',
        },
      },
      divideColor: {
        primary: 'var(--color-border-primary)',
        secondary: 'var(--color-border-secondary)',
        tertiary: 'var(--color-border-tertiary)',
      },
      fontSize: {
        badge: ['13.5px', { fontWeight: '500', lineHeight: '1.5' }],
        base: ['15.5px', { lineHeight: '1.5' }],
        body: ['15.5px', { lineHeight: '1.7' }],
        'card-title': ['18px', { fontWeight: '500', lineHeight: '1.5' }],
        chip: ['13px', { lineHeight: '1.5' }],
        h1: ['24px', { fontWeight: '500', lineHeight: '1.5' }],
        h2: ['20px', { fontWeight: '500', lineHeight: '1.5' }],
        // Typography scale from design system (in extend to preserve Tailwind defaults)
        overline: [
          '13px',
          { fontWeight: '500', letterSpacing: '0.5px', lineHeight: '1.5' },
        ],
        sm: ['15px', { lineHeight: '1.5' }],
        task: ['16px', { fontWeight: '500', lineHeight: '1.5' }],
        xs: ['13.5px', { lineHeight: '1.5' }],
      },
      fontWeight: {
        medium: '500',
        normal: '400',
      },
      height: {
        nav: '48px',
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
      },
      maxWidth: {
        'create-task': '680px',
        dashboard: '1400px',
        'project-detail': '1600px',
        'project-list': '1400px',
        settings: '1400px',
        'task-detail': '860px',
      },
      // ring-* colors mirror border tokens so status rings flip with theme
      ringColor: {
        accent: 'var(--color-border-accent)',
        danger: 'var(--color-border-danger)',
        info: 'var(--color-border-info)',
        primary: 'var(--color-border-primary)',
        secondary: 'var(--color-border-secondary)',
        success: 'var(--color-border-success)',
        tertiary: 'var(--color-border-tertiary)',
        warning: 'var(--color-border-warning)',
      },
      spacing: {
        'avatar-gap': '12px',
        'card-detail-x': '22px',
        'card-detail-y': '18px',
        'card-gap': '8px',
        'card-x': '18px',
        'card-y': '14px',
        'form-gap': '16px',
        'meta-gap': '8px',
        // Page and component spacing from design system
        'nav-height': '48px',
        'page-x': '20px',
        'page-y': '28px',
        'tab-panel': '22px',
        'tab-x': '18px',
        'tab-y': '11px',
      },
      // text-primary, text-secondary, text-tertiary, etc.
      textColor: {
        accent: 'var(--color-text-accent)',
        'action-foreground': 'var(--color-action-fg)',
        danger: 'var(--color-text-danger)',
        info: 'var(--color-text-info)',
        primary: 'var(--color-text-primary)',
        secondary: 'var(--color-text-secondary)',
        success: 'var(--color-text-success)',
        tertiary: 'var(--color-text-tertiary)',
        warning: 'var(--color-text-warning)',
      },
      transitionDuration: {
        fast: '100ms',
        progress: '200ms',
      },
      transitionProperty: {
        border: 'border-color',
      },
    },
    fontFamily: {
      mono: ['var(--font-mono)'],
      sans: ['var(--font-sans)'],
    },
  },
}
