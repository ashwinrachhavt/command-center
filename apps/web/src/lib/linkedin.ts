export function safeLinkedIn(value: string | null | undefined) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      (url.hostname === "linkedin.com" ||
        url.hostname.endsWith(".linkedin.com"))
      ? url.href
      : null;
  } catch {
    return null;
  }
}
