import { describe, expect, it } from "vitest";
import type { Habillage } from "./api";
import { fencedReducer, initialFenced } from "./fenced";
import { previewMonotone } from "./habillageEtat";

const etat = (champs: Partial<Habillage>) => ({ status: "", preview_ready: false, preview_v: 0, video_v: 0, ...champs }) as Habillage;

describe("previewMonotone", () => {
  it("never applies a preview_v lower than the last known", () => {
    const prev = etat({ preview_ready: true, preview_v: 200, status: "" });
    const next = etat({ preview_ready: true, preview_v: 100, status: "en_cours" });
    const m = previewMonotone(prev, next);
    expect(m.preview_v).toBe(200);
    expect(m.status).toBe("en_cours");          // the rest of the newer read is taken
  });

  it("takes a newer preview, and the first read as is", () => {
    expect(previewMonotone(etat({ preview_v: 100 }), etat({ preview_v: 300 })).preview_v).toBe(300);
    expect(previewMonotone(null, etat({ preview_v: 7 })).preview_v).toBe(7);
  });

  it("lets video_v fall back (a new rendering replaces the file)", () => {
    expect(previewMonotone(etat({ video_v: 50 }), etat({ video_v: 0 })).video_v).toBe(0);
  });

  it("holds through the fenced reducer: a late poll after « Update the preview » does not step back", () => {
    const r = fencedReducer<Habillage>(previewMonotone);
    let s = r(initialFenced(), { type: "loaded", data: etat({ preview_ready: true, preview_v: 100 }), seq: 0 });
    s = r(s, { type: "started", id: "apercu" });
    s = r(s, { type: "succeeded", id: "apercu", data: etat({ preview_ready: true, preview_v: 200 }) });
    // A read that left after the answer, served from an older snapshot.
    s = r(s, { type: "loaded", data: etat({ preview_ready: true, preview_v: 100 }), seq: s.seq });
    expect(s.server?.preview_v).toBe(200);
  });
});
