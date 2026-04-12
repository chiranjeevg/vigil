/**
 * Parse JSON response bodies safely (empty body, whitespace-only, invalid JSON).
 * Used by the API client so Settings and other pages never get silent failures
 * from `res.json()` throwing on empty 200 responses.
 */
export function parseJsonResponseBody(text: string): unknown {
  const trimmed = text.trim();
  if (trimmed === "") {
    return {};
  }
  return JSON.parse(trimmed) as unknown;
}
