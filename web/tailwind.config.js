/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./features/**/*.{js,ts,jsx,tsx,mdx}",
    "./shared/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        // Geist and Lora are Latin-only. Without an explicit CJK face after
        // them, Chinese fell through to the browser's generic `serif`/`sans`,
        // which differs per machine and per OS — a serif heading rendered its
        // Latin in Lora and its Chinese in whatever the browser happened to
        // pick. Naming the CJK faces makes both scripts deterministic and
        // pairs a Latin serif with a proper 宋体 rather than a stray fallback.
        //
        // Thai had the same hole and this fork is Thai-by-default, so the Thai
        // faces are named too: Sukhumvit Set is the modern macOS Thai UI face,
        // Thonburi covers older macOS, Leelawadee UI is Windows, Noto Sans Thai
        // is everywhere else. They sit ahead of the CJK block only for reading
        // order — neither script's fonts carry the other's glyphs, so they
        // cannot shadow each other, and Latin still resolves to Geist/Lora
        // first. Thai has no established serif tradition for UI, so the serif
        // chain leads with Noto Serif Thai where it exists and otherwise falls
        // back to the same Thai sans rather than to a stray generic.
        sans: [
          "var(--font-sans)",
          "Sukhumvit Set",
          "Thonburi",
          "Leelawadee UI",
          "Noto Sans Thai",
          "PingFang SC",
          "Hiragino Sans GB",
          "Microsoft YaHei",
          "Noto Sans SC",
          "system-ui",
          "sans-serif",
        ],
        serif: [
          "var(--font-serif)",
          "Noto Serif Thai",
          "Sukhumvit Set",
          "Thonburi",
          "Leelawadee UI",
          "Songti SC",
          "STSong",
          "Noto Serif SC",
          "Source Han Serif SC",
          "SimSun",
          "Georgia",
          "serif",
        ],
      },
      colors: {
        border: "var(--border)",
        input: "var(--input)",
        ring: "var(--ring)",
        background: "var(--background)",
        foreground: "var(--foreground)",
        primary: {
          DEFAULT: "var(--primary)",
          foreground: "var(--primary-foreground)",
        },
        secondary: {
          DEFAULT: "var(--secondary)",
          foreground: "var(--secondary-foreground)",
        },
        destructive: {
          DEFAULT: "var(--destructive)",
          foreground: "var(--destructive-foreground)",
        },
        muted: {
          DEFAULT: "var(--muted)",
          foreground: "var(--muted-foreground)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          foreground: "var(--accent-foreground)",
        },
        popover: {
          DEFAULT: "var(--popover)",
          foreground: "var(--popover-foreground)",
        },
        card: {
          DEFAULT: "var(--card)",
          foreground: "var(--card-foreground)",
        },
        success: {
          DEFAULT: "var(--success)",
          foreground: "var(--success-foreground)",
          surface: "var(--success-surface)",
        },
        warning: {
          DEFAULT: "var(--warning)",
          foreground: "var(--warning-foreground)",
          surface: "var(--warning-surface)",
        },
        info: {
          DEFAULT: "var(--info)",
          foreground: "var(--info-foreground)",
          surface: "var(--info-surface)",
        },
      },
      backgroundImage: {
        "gradient-radial": "radial-gradient(var(--tw-gradient-stops))",
        "gradient-conic":
          "conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))",
      },
    },
  },
  plugins: [],
};
