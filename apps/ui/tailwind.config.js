/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./app/**/*.{ts,tsx}",
    "./src/**/*.{ts,tsx}",
  ],
  prefix: "",
  theme: {
    container: {
      center: true,
      padding: "20px",
    },
    fontFamily: {
      sans: ["var(--font-sans)"],
      mono: ["var(--font-mono)"],
    },
    extend: {
      fontSize: {
        // Typography scale from design system (in extend to preserve Tailwind defaults)
        "overline": ["13px", { lineHeight: "1.5", letterSpacing: "0.5px", fontWeight: "500" }],
        "xs": ["13.5px", { lineHeight: "1.5" }],
        "chip": ["13px", { lineHeight: "1.5" }],
        "badge": ["13.5px", { lineHeight: "1.5", fontWeight: "500" }],
        "sm": ["15px", { lineHeight: "1.5" }],
        "base": ["15.5px", { lineHeight: "1.5" }],
        "task": ["16px", { lineHeight: "1.5", fontWeight: "500" }],
        "body": ["15.5px", { lineHeight: "1.7" }],
        "card-title": ["18px", { lineHeight: "1.5", fontWeight: "500" }],
        "h2": ["20px", { lineHeight: "1.5", fontWeight: "500" }],
        "h1": ["24px", { lineHeight: "1.5", fontWeight: "500" }],
      },
      borderWidth: {
        DEFAULT: "0.5px",
        0: "0",
        2: "2px",
      },
      fontWeight: {
        normal: "400",
        medium: "500",
      },
      borderRadius: {
        DEFAULT: "4px",
        none: "0",
        sm: "4px",
        md: "var(--border-radius-md)",
        lg: "var(--border-radius-lg)",
        full: "9999px",
      },
      // Separate bg/text/border color mappings for clean utility names
      // bg-primary, bg-secondary, bg-tertiary, etc.
      backgroundColor: {
        primary: "var(--color-background-primary)",
        secondary: "var(--color-background-secondary)",
        tertiary: "var(--color-background-tertiary)",
        info: "var(--color-background-info)",
        danger: "var(--color-background-danger)",
        success: "var(--color-background-success)",
        warning: "var(--color-background-warning)",
      },
      // text-primary, text-secondary, text-tertiary, etc.
      textColor: {
        primary: "var(--color-text-primary)",
        secondary: "var(--color-text-secondary)",
        tertiary: "var(--color-text-tertiary)",
        info: "var(--color-text-info)",
        danger: "var(--color-text-danger)",
        success: "var(--color-text-success)",
        warning: "var(--color-text-warning)",
      },
      // border-primary, border-secondary, border-tertiary, etc.
      borderColor: {
        primary: "var(--color-border-primary)",
        secondary: "var(--color-border-secondary)",
        tertiary: "var(--color-border-tertiary)",
        info: "var(--color-border-info)",
      },
      colors: {
        // shadcn/ui compatibility (used by button, badge, dialog, dropdown, popover, etc.)
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        // WorkerBee amber brand palette (hardcoded per design system)
        amber: {
          bg: "#faeeda",
          border: "#ef9f27",
          text: "#7c5900",
          "text-mid": "#ba7517",
          "border-strong": "#854f0b",
        },
        // Task status colors
        "status-queued": {
          dot: "#888780",
          bg: "#f1efe8",
          text: "#444441",
        },
        "status-feedback": {
          dot: "#ef9f27",
          bg: "#faeeda",
          text: "#7c5900",
        },
        "status-implementing": {
          dot: "#7f77dd",
          bg: "#eeedfe",
          text: "#3c3489",
        },
        "status-review": {
          dot: "#639922",
          bg: "#eaf3de",
          text: "#27500a",
        },
        "status-failed": {
          dot: "#e24b4a",
          bg: "#fcebeb",
          text: "#791f1f",
        },
        // Link type colors
        "link-related": {
          bg: "#e6f1fb",
          text: "#185fa5",
        },
        "link-blocks": {
          bg: "#fcebeb",
          text: "#a32d2d",
        },
        "link-followup": {
          bg: "#eeedfe",
          text: "#3c3489",
        },
        // Avatar fallback
        "avatar-default": {
          bg: "#f1efe8",
          text: "#5f5e5a",
        },
      },
      maxWidth: {
        dashboard: "1400px",
        "project-list": "1400px",
        "project-detail": "1600px",
        settings: "1400px",
        "task-detail": "860px",
        "create-task": "680px",
      },
      spacing: {
        // Page and component spacing from design system
        "nav-height": "48px",
        "page-x": "20px",
        "page-y": "28px",
        "card-x": "18px",
        "card-y": "14px",
        "card-detail-x": "22px",
        "card-detail-y": "18px",
        "tab-x": "18px",
        "tab-y": "11px",
        "tab-panel": "22px",
        "form-gap": "16px",
        "meta-gap": "8px",
        "avatar-gap": "12px",
        "card-gap": "8px",
      },
      height: {
        nav: "48px",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
      transitionProperty: {
        border: "border-color",
      },
      transitionDuration: {
        fast: "100ms",
        progress: "200ms",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
