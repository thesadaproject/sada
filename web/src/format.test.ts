import { describe, expect, it } from "vitest";
import { heureDuJour } from "./format";

describe("heureDuJour", () => {
  it("always shows the hours, even just after midnight", () => {
    expect(heureDuJour(49 * 60 + 38)).toBe("00:49:38");
    expect(heureDuJour(13 * 3600 + 5)).toBe("13:00:05");
  });
  it("wraps around the day", () => {
    expect(heureDuJour(86400 + 61)).toBe("00:01:01");
    expect(heureDuJour(-1)).toBe("23:59:59");
  });
});
