import { Link } from "react-router-dom";

export function BrandLogo({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const h = size === "sm" ? 28 : size === "lg" ? 56 : 36;
  return <img src="/logo.svg" alt="Kindling" style={{ height: h }} />;
}

export function BrandMark({ size = 32 }: { size?: number }) {
  return <img src="/logo-mark.svg" alt="" width={size} height={size} />;
}

export function Brand({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <Link to="/dashboard" className="flex items-center gap-2 font-semibold">
      <BrandMark size={32} />
      {!collapsed && <span className="text-base">Kindling</span>}
    </Link>
  );
}
