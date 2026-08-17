import { Link } from "react-router-dom";

// Vite replaces import.meta.env.BASE_URL with the configured `base` value
// at build time, so these assets resolve at /logo.svg in dev (no base) and
// /kindling/logo.svg in production.
const BASE = import.meta.env.BASE_URL;

export function BrandLogo({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const h = size === "sm" ? 28 : size === "lg" ? 56 : 36;
  return <img src={`${BASE}logo.svg`} alt="Kindling" style={{ height: h }} />;
}

export function BrandMark({ size = 32 }: { size?: number }) {
  return <img src={`${BASE}logo-mark.svg`} alt="" width={size} height={size} />;
}

export function Brand({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <Link
      to="/kindling/dashboard"
      className="flex items-center gap-2 font-semibold"
      // The mark is decorative, so when the label is hidden the link needs an
      // explicit name or it is announced as an unlabelled "link".
      aria-label={collapsed ? "Kindling" : undefined}
    >
      <BrandLogo size="sm" />
      {/* BrandLogo's SVG already renders the "kindling" wordmark; an
          adjacent <span> would produce a visible double wordmark. The
          `aria-label` above covers the collapsed case. */}
    </Link>
  );
}
