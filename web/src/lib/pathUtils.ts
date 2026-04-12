/** Compare absolute project paths from UI / API (OS may differ in slash style). */
export function pathsEqual(
  a: string | undefined | null,
  b: string | undefined | null,
): boolean {
  if (a == null || b == null) return false;
  const sa = String(a).trim();
  const sb = String(b).trim();
  if (!sa || !sb) return false;
  const norm = (s: string) =>
    s.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  return norm(sa) === norm(sb);
}

/** Row shape used by Dashboard / Logs / Settings project pickers */
export interface VigilProjectListItem {
  name: string;
  path: string;
  has_config: boolean;
  has_state: boolean;
  iteration_count: number;
}
