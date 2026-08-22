/** Single source of truth for the ScriptNew default name.
 *
 * Mirrors `kindling.api.scripts.UNTITLED_PLACEHOLDER` on the backend — both
 * layers reject the same literal so a placeholder row can never land in the
 * DB. Keep the strings in sync.
 */
export const UNTITLED_PLACEHOLDER = "untitled script";

export function isPlaceholderName(name: string): boolean {
  return name.trim().toLowerCase() === UNTITLED_PLACEHOLDER;
}
