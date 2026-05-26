/** Safety helpers — client-side validation before any action request. */

export const LOCALHOST_ORIGINS = ["http://127.0.0.1", "http://localhost", "http://[::1]"];

export function isLocalhostOrigin(): boolean {
  return LOCALHOST_ORIGINS.some((o) => window.location.href.startsWith(o));
}

export function assertReadOnly(mode: string): void {
  if (mode !== "read_only_v1") {
    throw new Error(`Unexpected mode: ${mode}. Expected read_only_v1.`);
  }
}
