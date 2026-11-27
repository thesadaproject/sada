// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: "fr" } }),
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

  it("off air, a scene starts the live only once confirmed", async () => {
    await monter();
    confirm.mockResolvedValue(false);
    await act(async () => { fireEvent.click(sceneButton("dashboard.choice.khutba")); });
    expect(confirm).toHaveBeenCalledWith(expect.objectContaining({ message: "regie.sceneStartsLive" }));
    expect(api.regieScene).not.toHaveBeenCalled();
    confirm.mockResolvedValue(true);
    await act(async () => { fireEvent.click(sceneButton("dashboard.choice.khutba")); });
    expect(api.regieScene).toHaveBeenCalledWith("khutba", "fade");
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

  it("says when no studio is paired", async () => {
    await monter({ ...offAir, studios: [] });
    expect(screen.getByText(/regie.noStudio\b(?!Hint)/)).toBeTruthy();
    expect(screen.getByText("regie.noStudioHint")).toBeTruthy();
    expect(screen.getByRole("link", { name: "regie.pairStudio" }).getAttribute("href")).toBe("/appareils");
  });
});
