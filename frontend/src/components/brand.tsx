import { Link } from "react-router-dom";

export function Brand({ collapsed = false }: { collapsed?: boolean }) {
  return (
    <Link to="/dashboard" className="flex items-center gap-2 font-semibold">
      <div className="grid h-8 w-8 place-items-center rounded-md bg-primary text-primary-foreground">
        S
      </div>
      {!collapsed && <span className="text-base">ScriptDeck</span>}
    </Link>
  );
}