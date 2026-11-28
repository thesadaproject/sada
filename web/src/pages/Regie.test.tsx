// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, o?: { time?: string }) => (o?.time ? `${k} ${o.time}` : k), i18n: { language: "fr" } }),
}));
const api = vi.hoisted(() => ({
  regie: vi.fn(), regieScene: vi.fn(), regiePreview: vi.fn(), regieOverlay: vi.fn(), regieTransition: vi.fn(),
  regieMute: vi.fn(), liveCommande: vi.fn(), studioTakeover: vi.fn(),
}));
vi.mock("../api", () => ({ api, ApiError: class extends Error { status = 0; } }));
vi.mock("../monitor", () => ({ playMonitor: vi.fn(() => () => undefined) }));

import type { Session } from "../api";
import { ConfirmContext, type Confirm } from "../confirmContext";
import { setCurrentSession } from "../session";
import { makeStore } from "../store";
import Regie from "./Regie";

const scenes = [
  { id: "avant", scene_kind: "full", label: "avant" },
  { id: "khutba", scene_kind: "banner", label: "khutba" },
  { id: "custom:affiche", scene_kind: "full", label: "Affiche de l'Aïd", custom: true },
];
const commands = ["start", "pause", "stop", "extend", "skip", "auto", "scene", "janaza", "tarawih"]
  .map((key) => ({ key, destructive: key === "stop", choices: key === "extend" ? ["5"] : [] }));
const offAir = {
  live: { ok: true, state: "IDLE", scene: null, stream_on: false, override: false, transition: "fade",
          overlays: { qr: { visible: false, url: "", label: "", corner: "tr" }, banner: { visible: false, title: "", subtitle: "" }, logo: { visible: false } } },
  commands, scenes, monitors: { source: { available: false, health: null }, program: { available: false, health: null }, preview: { available: false, health: null } },
  publisher: null, audio: { mic_on: false, muted: false, level_db: null },
  studios: [{ id: 3, name: "PC salle", online: true, publishing: false, camera: true, microphone: true }],
  preview: { requested: false },
};

let confirm: ReturnType<typeof vi.fn<Confirm>>;

async function monter(payload: unknown = offAir) {
  api.regie.mockResolvedValue(payload);
  setCurrentSession({ user: { permissions: ["live"] } } as unknown as Session);
  render(
    <ConfirmContext value={confirm}>
      <Provider store={makeStore()}><MemoryRouter><Regie /></MemoryRouter></Provider>
    </ConfirmContext>,
  );
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

const sceneButton = (label: string) => screen.getByRole("button", { name: new RegExp(label) });

describe("Régie (remote control of the Sada Studio)", () => {
  beforeEach(() => {
    confirm = vi.fn<Confirm>();
    for (const f of Object.values(api)) f.mockReset();
    api.regieScene.mockResolvedValue({ ok: true });
    api.regiePreview.mockResolvedValue({ ok: true, requested: true });
    api.regieOverlay.mockResolvedValue({ ok: true });
  });
  afterEach(() => { cleanup(); setCurrentSession(null); });

  it("signal lost: a banner counts down to the automatic end, from the server's remaining time", async () => {
    vi.useFakeTimers();
    try {
      const live = { ...offAir.live, state: "KHUTBA", scene: "khutba", stream_on: true, fallback_remaining_s: 72, fallback_until: 1, signal_lost_since: 0 };
      await monter({ ...offAir, live });
      expect(screen.getByRole("alert").textContent).toContain("regie.signalLost");
      expect(screen.getByRole("alert").textContent).toContain("regie.signalLostCountdown 1:12");
      await act(async () => { await vi.advanceTimersByTimeAsync(1_000); });
      expect(screen.getByRole("alert").textContent).toContain("regie.signalLostCountdown 1:11");
      api.regie.mockRejectedValue(new Error("offline"));  // no newer read: the countdown runs on its own
      await act(async () => { await vi.advanceTimersByTimeAsync(200_000); });
      expect(screen.getByRole("alert").textContent).toContain("regie.signalLostCountdown 0:00");  // never negative
    } finally {
      vi.useRealTimers();
    }
  });

  it("a tarawih night, ten minutes of grace: the banner starts from the server's 10:00", async () => {
    const live = { ...offAir.live, state: "TARAWIH", scene: "tarawih", stream_on: true, fallback_remaining_s: 600, fallback_until: 1, signal_lost_since: 0 };
    await monter({ ...offAir, live });
    expect(screen.getByRole("alert").textContent).toContain("regie.signalLostCountdown 10:00");
  });

  it("a live started by hand says so, and that only Stop ends it", async () => {
    const live = { ...offAir.live, state: "BEFORE", scene: "avant", stream_on: true, override: true, manual_live: true };
    await monter({ ...offAir, live });
    expect(screen.getByText("regie.manualLive")).toBeTruthy();
    expect(screen.getByText("regie.manualLiveHintOverride")).toBeTruthy();
    cleanup();
    await monter({ ...offAir, live: { ...live, override: false } });
    expect(screen.getByText("regie.manualLiveHintAuto")).toBeTruthy();
    cleanup();
    await monter({ ...offAir, live: { ...live, manual_live: false, override: true } });  // a planned session in override
    expect(screen.getByText("regie.manualHint")).toBeTruthy();
  });

  it("no banner while the live has its signal, nor off air", async () => {
    await monter({ ...offAir, live: { ...offAir.live, state: "KHUTBA", stream_on: true, fallback_remaining_s: null } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("off air, a scene only changes the picture: no confirmation, no live shown", async () => {
    await monter();
    await act(async () => { fireEvent.click(sceneButton("dashboard.choice.khutba")); });
    expect(confirm).not.toHaveBeenCalled();
    expect(api.regieScene).toHaveBeenCalledWith("khutba", "fade");
    expect(screen.queryByText("dashboard.liveOn")).toBeNull();
  });

  it("on air, a scene (custom ones too) is taken at once", async () => {
    await monter({ ...offAir, live: { ...offAir.live, state: "KHUTBA", scene: "khutba", stream_on: true } });
    await act(async () => { fireEvent.click(sceneButton("Affiche de l'Aïd")); });
    expect(confirm).not.toHaveBeenCalled();
    expect(api.regieScene).toHaveBeenCalledWith("custom:affiche", "fade");
  });

  it("has no janaza form any more", async () => {
    await monter();
    expect(screen.queryByText("dashboard.janaza")).toBeNull();
    expect(screen.queryByPlaceholderText("dashboard.janazaName")).toBeNull();
  });

  it("asks the studio for its picture only while the monitor shows it", async () => {
    await monter();
    expect(screen.getByText("PC salle")).toBeTruthy();
    expect(api.regiePreview).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "regie.studioFeedShow" })); });
    expect(api.regiePreview).toHaveBeenCalledWith(true);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "regie.studioFeedStop" })); });
    expect(api.regiePreview).toHaveBeenLastCalledWith(false);
  });

  it("shows a banner with the typed title", async () => {
    await monter();
    fireEvent.change(screen.getByPlaceholderText("regie.bannerTitle"), { target: { value: "Collecte" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "regie.show — regie.banner" })); });
    expect(api.regieOverlay).toHaveBeenCalledWith("banner", { visible: true, title: "Collecte", subtitle: "" });
  });

  it("shows what the studio gives next to what goes on air", async () => {
    await monter({ ...offAir, live: { ...offAir.live, state: "KHUTBA", stream_on: true },
                   studios: [{ ...offAir.studios[0], publishing: true }] });
    expect(screen.getByText("regie.studioFeed")).toBeTruthy();
    expect(screen.getByText("regie.studioStreamHint")).toBeTruthy();
    expect(screen.getByText("regie.program")).toBeTruthy();
    expect(screen.getByText("regie.programWaiting")).toBeTruthy();
  });

  it("on air without the studio's picture, Start orders the studio again and says what happened", async () => {
    api.liveCommande.mockResolvedValue({ ok: true, message: "ok", studio: "no_studio" });
    await monter({ ...offAir, live: { ...offAir.live, state: "BEFORE", stream_on: true } });
    expect(screen.getByText("regie.programWaiting")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "dashboard.cmd.start" })); });
    expect(api.liveCommande).toHaveBeenCalledWith("start", {});
    expect(screen.getByRole("status").textContent).toBe("regie.studioNotThere");
  });

  it("hides « the picture arrives shortly » as soon as the programme picture is there", async () => {
    api.liveCommande.mockResolvedValue({ ok: true, message: "ok", studio: "ordered" });
    const live = { ...offAir.live, state: "BEFORE", stream_on: true };
    await monter({ ...offAir, live });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "dashboard.cmd.start" })); });
    expect(screen.getByRole("status").textContent).toBe("regie.studioOrdered");
    // the next poll brings the picture (the tab coming back to the front polls at once)
    api.regie.mockResolvedValue({ ...offAir, live, monitors: { ...offAir.monitors, program: { available: true, health: null } } });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("keeps « the picture arrives shortly » while there is no picture yet", async () => {
    api.liveCommande.mockResolvedValue({ ok: true, message: "ok", studio: "ordered" });
    await monter({ ...offAir, live: { ...offAir.live, state: "BEFORE", stream_on: true } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "dashboard.cmd.start" })); });
    expect(screen.getByRole("status").textContent).toBe("regie.studioOrdered");
  });

  it("says when no studio is paired", async () => {
    await monter({ ...offAir, studios: [] });
    expect(screen.getByText(/regie.noStudio\b(?!Hint)/)).toBeTruthy();
    expect(screen.getByText("regie.noStudioHint")).toBeTruthy();
    expect(screen.getByRole("link", { name: "regie.pairStudio" }).getAttribute("href")).toBe("/appareils");
  });
});
