/** The system of the computer showing the page (the one people usually install the Sada Studio on). */
export function systeme(ua: string = navigator.userAgent): "windows" | "mac" | "linux" | null {
  if (/Windows/i.test(ua)) return "windows";
  if (/Mac OS X|Macintosh/i.test(ua) && !/iPhone|iPad/i.test(ua)) return "mac";
  if (/Linux/i.test(ua) && !/Android/i.test(ua)) return "linux";
  return null;
}
