import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        night: "#071a2e",
        primary: "#1f6bb4",
        primaryHover: "#0f4f8c",
        deep: "#08253f",
        softStart: "#f3f8fd",
        softMid: "#eef5fb",
        softEnd: "#e4edf7",
        surface: "#f5f9fd",
        borderSoft: "#d6e2ef",
        secondaryText: "#4c6480",
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "Arial", "sans-serif"],
        mono: ["Fira Code", "Consolas", "monospace"],
      },
      boxShadow: {
        panel: "0 1px 2px rgba(7, 26, 46, 0.08)",
      },
    },
  },
  plugins: [],
} satisfies Config;
