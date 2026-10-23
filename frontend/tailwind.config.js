/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#F1F0FE", 100: "#E4E2FD", 200: "#CBC7FB", 300: "#ADA6F7",
          400: "#8E85F2", 500: "#6C63E8", 600: "#5B57E8", 700: "#4842C9",
          800: "#3A35A3", 900: "#2F2B80"
        },
        teal: { 400: "#2DD4BF", 500: "#14B8A6", 600: "#0EA5A5", 700: "#0F766E" },
        ink: { 900: "#171A23", 800: "#1F2430", 700: "#333A49", 600: "#4B5466", 500: "#6B7280", 400: "#8B93A7", 300: "#B4BAC9" },
        surface: { 0: "#FFFFFF", 50: "#FAFBFD", 100: "#F5F6FA", 200: "#EFF1F7", 300: "#E6E9F2" },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"PingFang SC"', '"Microsoft YaHei"', '"Segoe UI"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      boxShadow: {
        card: "0 1px 2px rgba(23,26,35,.04), 0 8px 24px -12px rgba(23,26,35,.10)",
        pop: "0 12px 40px -12px rgba(23,26,35,.24)",
      },
      borderRadius: { xl: "14px", "2xl": "18px" },
      keyframes: {
        "fade-in": { from: { opacity: 0, transform: "translateY(6px)" }, to: { opacity: 1, transform: "none" } },
        "pulse-soft": { "0%,100%": { opacity: 1 }, "50%": { opacity: .45 } },
        "slide-in": { from: { opacity: 0, transform: "translateX(12px)" }, to: { opacity: 1, transform: "none" } },
      },
      animation: {
        "fade-in": "fade-in .28s ease-out both",
        "pulse-soft": "pulse-soft 1.6s ease-in-out infinite",
        "slide-in": "slide-in .24s ease-out both",
      },
    },
  },
  plugins: [],
};
