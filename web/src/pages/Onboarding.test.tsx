// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// A stable `t`, as the real one: the page reads its settings again when `t` changes.
const i18n = vi.hoisted(() => ({ t: (k: string) => k, i18n: { language: "fr" } }));
vi.mock("react-i18next", () => ({ useTranslation: () => i18n }));
const api = vi.hoisted(() => ({
  settings: vi.fn(), studioDownload: vi.fn(), studioDevices: vi.fn(), studioPair: vi.fn(),
  saveInput: vi.fn(), testInput: vi.fn(), destinations: vi.fn(), prayerSave: vi.fn(), onboardingDone: vi.fn(),
}));
vi.mock("../api", () => ({ api, ApiError: class extends Error { status = 0; } }));
vi.mock("../PrayerFields", () => ({ Apercu: () => null, CalcFields: () => null }));

import { systeme } from "../systeme";
import Onboarding from "./Onboarding";

const RELEASE = {
  version: "0.6.0", page: "https://github.com/thesadaproject/sada-studio/releases/tag/v0.6.0",
  assets: { windows: "https://dl/setup.exe", mac_arm64: "https://dl/arm64.dmg", mac_x64: "https://dl/x64.dmg", linux: "https://dl/app.AppImage" },
};

function settings(modes: string[], mode = "push", configured = false) {
  return { input: { mode, url: "", push_rtmp: "rtmp://relay/live/x", configured, modes }, targets: [], prayer: {} };
}

async function monter() {
  render(<MemoryRouter><Onboarding /></MemoryRouter>);
  await act(async () => { for (let i = 0; i < 4; i++) await Promise.resolve(); });
}

describe("getting started: the picture comes from the Sada Studio", () => {
  beforeEach(() => {
    for (const f of Object.values(api)) f.mockReset();
    api.studioDownload.mockResolvedValue(RELEASE);
    api.studioDevices.mockResolvedValue({ devices: [] });
  });
  afterEach(() => cleanup());

  it("hosted: no OBS address at all, the studio to download and link", async () => {
    api.settings.mockResolvedValue(settings(["push"]));
    await monter();
    expect(screen.queryByDisplayValue("rtmp://relay/live/x")).toBeNull();
    expect(screen.queryByText("onboarding.pushServer")).toBeNull();
    expect(screen.getByText("onboarding.dlTitle")).toBeTruthy();
    expect(screen.getByRole("link", { name: "onboarding.dlAll" }).getAttribute("href")).toBe(RELEASE.page);
    expect(screen.getByText("onboarding.pairStep")).toBeTruthy();
    // the server cannot reach a camera inside the mosque: not offered at all
    expect(screen.queryByText("onboarding.cameraTitle")).toBeNull();
    expect(screen.queryByText("onboarding.cameraUrl")).toBeNull();
  });

  it("shows no camera while the settings load", async () => {
    api.settings.mockReturnValue(new Promise(() => undefined));
    await monter();
    expect(screen.queryByText("onboarding.cameraTitle")).toBeNull();
    expect(screen.getByText("onboarding.dlTitle")).toBeTruthy();
  });

  it("self-hosted: the studio first and chosen, the camera still offered", async () => {
    api.settings.mockResolvedValue(settings(["camera", "push"], "camera"));
    await monter();
    const choix = screen.getAllByRole("button").filter((b) => /onboarding\.(studio|camera)Title/.test(b.textContent ?? ""));
    expect(choix.map((b) => b.textContent?.includes("studioTitle"))).toEqual([true, false]);
    expect(screen.getByText("onboarding.dlTitle")).toBeTruthy();
    fireEvent.click(choix[1]);
    expect(screen.getByText("onboarding.cameraUrl")).toBeTruthy();
  });

  it("a camera already set up stays chosen", async () => {
    api.settings.mockResolvedValue(settings(["camera", "push"], "camera", true));
    await monter();
    expect(screen.getByText("onboarding.cameraUrl")).toBeTruthy();
  });

  it("links the studio with the code it shows, then sees it online", async () => {
    api.settings.mockResolvedValue(settings(["push"]));
    api.studioPair.mockResolvedValue({ ok: true, message: "Appareil appairé." });
    await monter();
    fireEvent.change(screen.getByPlaceholderText("ABCD-2345"), { target: { value: "ABCD-2345" } });
    fireEvent.change(screen.getByPlaceholderText("devices.namePlaceholder"), { target: { value: "PC salle" } });
    api.studioDevices.mockResolvedValue({ devices: [{ id: 1, name: "PC salle", online: true, revoked: false }] });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "onboarding.pair" })); });
    expect(api.studioPair).toHaveBeenCalledWith("ABCD-2345", "PC salle");
    expect(screen.getByText("Appareil appairé.")).toBeTruthy();
    expect(screen.getByText("onboarding.deviceOnline")).toBeTruthy();
    expect(screen.getByText("onboarding.pairedHint")).toBeTruthy();
  });
});

describe("system of the visitor", () => {
  it("offers the installer of the computer showing the page", () => {
    expect(systeme("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("windows");
    expect(systeme("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)")).toBe("mac");
    expect(systeme("Mozilla/5.0 (X11; Linux x86_64)")).toBe("linux");
    expect(systeme("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")).toBeNull();
    expect(systeme("Mozilla/5.0 (Linux; Android 14)")).toBeNull();
  });
});
