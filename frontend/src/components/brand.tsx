import { Link } from "react-router-dom";

// Vite replaces import.meta.env.BASE_URL with the configured `base` value
// at build time, so these assets resolve at /logo.svg in dev (no base) and
// /kindling/logo.svg in production.
const BASE = import.meta.env.BASE_URL;

// Full lockup (mark + wordmark + tagline) for the auth screens where there
// is room and the tagline adds context.
export function BrandLogo({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const h = size === "sm" ? 32 : size === "lg" ? 96 : 56;
  return (
    <img
      src={`${BASE}logo.svg`}
      alt="Kindling"
      style={{ height: h }}
      className="text-foreground"
    />
  );
}

// Compact lockup (mark + wordmark, no tagline) for the app sidebar. The
// wordmark uses the same amber→cream→red gradient as the auth screen, baked
// into the SVG so the gradient renders correctly even on the dark sidebar.
export function BrandSidebar({ height = 40 }: { height?: number }) {
  return (
    <img
      src={`${BASE}logo-sidebar.svg`}
      alt="Kindling"
      style={{ height }}
    />
  );
}

// Just the mark, for callers that want mark-only (rare — sidebar uses the
// compact lockup instead so the wordmark is always visible).
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

// Sidebar / collapsed nav: compact mark + wordmark lockup. The brand link
// gets an explicit accessible name; the image alt is redundant but
// preserved for assistive tech that doesn't traverse the wrapping link.
export function Brand() {
  return (
    <Link
      to="/kindling/dashboard"
      className="flex items-center"
      aria-label="Kindling"
    >
      <BrandSidebar height={40} />
    </Link>
  );
}