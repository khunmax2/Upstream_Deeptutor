/**
 * Hand-drawn illustration icons for the Learner Anima dashboard — richer than the
 * flat lucide line icons (colored fills, soft shading, small details) to match the
 * warm, friendly look the user approved. Pure inline SVG: no external asset, no new
 * dependency, self-contained and CSP-safe. Sized by the `className` (e.g. h-6 w-6).
 */

export function BookIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 40 40"
      className={className}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="anima-book-cover" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#e0895e" />
          <stop offset="1" stopColor="#b0501e" />
        </linearGradient>
      </defs>
      {/* ground shadow */}
      <ellipse
        cx="20"
        cy="35.5"
        rx="12"
        ry="2.2"
        fill="#000000"
        opacity="0.12"
      />
      {/* page block + fore-edge */}
      <rect x="10" y="6.5" width="21" height="28" rx="3" fill="#f7eede" />
      <rect x="26.5" y="6.5" width="4.5" height="28" rx="2.2" fill="#eaddc2" />
      <g stroke="#ddcba8" strokeWidth="1" strokeLinecap="round">
        <line x1="28" y1="10.5" x2="28" y2="30.5" />
        <line x1="29.6" y1="10.5" x2="29.6" y2="30.5" />
      </g>
      {/* page lines peeking under the cover */}
      <g stroke="#e4d5b8" strokeWidth="1.4" strokeLinecap="round">
        <line x1="15" y1="24" x2="24" y2="24" />
        <line x1="15" y1="27.5" x2="22" y2="27.5" />
      </g>
      {/* front cover */}
      <rect
        x="7"
        y="5.5"
        width="20"
        height="29"
        rx="3.2"
        fill="url(#anima-book-cover)"
      />
      {/* spine */}
      <rect x="7" y="5.5" width="5" height="29" rx="2.6" fill="#8f4317" />
      <line
        x1="12"
        y1="6.5"
        x2="12"
        y2="33.5"
        stroke="#000000"
        opacity="0.14"
        strokeWidth="1"
      />
      {/* cover sheen */}
      <rect
        x="14.5"
        y="8.5"
        width="9"
        height="2.2"
        rx="1.1"
        fill="#ffffff"
        opacity="0.4"
      />
      <rect
        x="14.5"
        y="12.5"
        width="6"
        height="1.8"
        rx="0.9"
        fill="#ffffff"
        opacity="0.28"
      />
      {/* emblem */}
      <circle cx="18.5" cy="21" r="3.4" fill="#ffd98a" />
      <path
        d="M18.5 18.7l0.8 1.6 1.8 0.26-1.3 1.27 0.3 1.77-1.6-0.84-1.6 0.84 0.3-1.77-1.3-1.27 1.8-0.26z"
        fill="#b0501e"
      />
      {/* bookmark ribbon */}
      <path d="M21.5 5.5h3.2v7.4l-1.6-1.5-1.6 1.5z" fill="#5fa892" />
    </svg>
  );
}
