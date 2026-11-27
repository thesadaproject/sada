import { describe, expect, it } from "vitest";

import type { Session } from "./api";
import { proposerDemarrage } from "./demarrage";

const session = (needs: boolean, permissions = ["admin"]) =>
  ({ mosque: { needs_onboarding: needs }, user: { permissions } }) as unknown as Session;

describe("setup wizard proposal", () => {
  it("is offered to an admin landing on the home page of an unfinished mosque", () => {
    expect(proposerDemarrage(session(true), "/")).toBe(true);
  });

  it("never overrides the settings (gear, bookmark or reload on /settings)", () => {
    expect(proposerDemarrage(session(true), "/settings")).toBe(false);
    expect(proposerDemarrage(session(true), "/audit")).toBe(false);
    expect(proposerDemarrage(session(true), "/regie")).toBe(false);
  });

  it("is not offered once set up, to a non-admin, or without a session", () => {
    expect(proposerDemarrage(session(false), "/")).toBe(false);
    expect(proposerDemarrage(session(true, ["live"]), "/")).toBe(false);
    expect(proposerDemarrage(null, "/")).toBe(false);
  });
});
