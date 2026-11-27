import type { Session } from "./api";

/** First login of an administrator whose mosque is not set up yet: the wizard is offered once, and only when
 *  they land on the home page. A deliberate destination (the settings gear, a bookmark, a reload on another
 *  page) is never overridden. */
export function proposerDemarrage(session: Session | null, pathname: string): boolean {
  if (!session || pathname !== "/") return false;
  return !!session.mosque?.needs_onboarding && session.user.permissions.includes("admin");
}
