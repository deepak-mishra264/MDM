export default function Logo({ className = "h-6 w-6" }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="searce-mdm-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#1A73E8" />
          <stop offset="100%" stopColor="#188038" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="28" height="28" rx="7" fill="url(#searce-mdm-grad)" />
      <path
        d="M9 11.5C9 9.567 10.567 8 12.5 8h7A3.5 3.5 0 0 1 23 11.5v0a3.5 3.5 0 0 1-3.5 3.5H12.5"
        stroke="#fff" strokeWidth="2.2" fill="none" strokeLinecap="round"
      />
      <path
        d="M23 20.5C23 22.433 21.433 24 19.5 24h-7A3.5 3.5 0 0 1 9 20.5v0A3.5 3.5 0 0 1 12.5 17h7"
        stroke="#fff" strokeWidth="2.2" fill="none" strokeLinecap="round"
      />
      <circle cx="12.5" cy="11.5" r="1.2" fill="#fff" />
      <circle cx="19.5" cy="20.5" r="1.2" fill="#fff" />
    </svg>
  );
}
