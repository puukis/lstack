/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--bg)",
        foreground: "var(--fg)",
        card: { DEFAULT: "var(--panel)", foreground: "var(--fg)" },
        panel: { DEFAULT: "var(--panel)", subtle: "var(--panel-2)" },
        border: "var(--border)",
        "border-strong": "var(--border-strong)",
        muted: { DEFAULT: "var(--panel-2)", foreground: "var(--fg-2)" },
        primary: { DEFAULT: "var(--accent)", foreground: "var(--fg)" },
        secondary: { DEFAULT: "var(--panel-2)", foreground: "var(--fg)" },
        destructive: { DEFAULT: "var(--danger)", foreground: "#ffffff" },
        accent: { DEFAULT: "var(--accent)", foreground: "var(--accent-text)", dim: "var(--accent-dim)" },
        warn: { DEFAULT: "var(--warn)", dim: "var(--warn-dim)" },
        danger: { DEFAULT: "var(--danger)", dim: "var(--danger-dim)" },
        "fg-2": "var(--fg-2)",
        "fg-3": "var(--fg-3)",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      boxShadow: {
        atelier: "var(--shadow)",
      },
    },
  },
  plugins: [],
};
