import { Link } from "react-router-dom";

// Vite replaces import.meta.env.BASE_URL with the configured `base` value
// at build time, so these assets resolve at /logo.svg in dev (no base) and
// /kindling/logo.svg in production.
const BASE = import.meta.env.BASE_URL;

// Combined mark + wordmark, for surfaces that have room (login, setup).
// `currentColor` lets the host's CSS color property drive the wordmark ink.
export function BrandLogo({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const h = size === "sm" ? 32 : size === "lg" ? 72 : 48;
  return (
    <img
      src={`${BASE}logo.svg`}
      alt="Kindling"
      style={{ height: h }}
      className="text-foreground"
    />
  );
}

// Just the mark, for surfaces where the wordmark would be illegible at the
// available size (sidebar at h-14). Sized in px so callers can override.
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <img
      src={`${BASE}logo-mark.svg`}
      alt=""
      width={size}
      height={size}
    />
  );
}

// Sidebar / collapsed nav: mark only. The brand link gets an explicit
// accessible name because the image is decorative.
export function Brand() {
  return (
    <Link
      to="/kindling/dashboard"
      className="flex items-center gap-2 font-semibold"
      aria-label="Kindling"
    >
      <BrandMark />
    </Link>
  );
}
