// @vitest-environment happy-dom
import { useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// A stable `t`, as the real one.
const i18n = vi.hoisted(() => ({ t: (k: string) => k, i18n: { language: "fr" } }));
vi.mock("react-i18next", () => ({ useTranslation: () => i18n }));
const api = vi.hoisted(() => ({
  revokeStreamKey: vi.fn(), studioDownload: vi.fn(), studioDevices: vi.fn(), studioPair: vi.fn(), testInput: vi.fn(),
}));
vi.mock("../api", () => ({ api, ApiError: class extends Error { status = 0; } }));

import { ConfirmContext, type Confirm } from "../confirmContext";
import { EntreeVideo, type Entree } from "./EntreeVideo";

let confirm: ReturnType<typeof vi.fn<Confirm>>;
const revoked = vi.fn();

function Page({ initial }: { initial: Entree }) {
  const [entree, setEntree] = useState(initial);
  return <EntreeVideo entree={entree} setEntree={setEntree} onKeyRevoked={revoked} />;
}

async function monter(e: Partial<Entree>) {
  const initial: Entree = { mode: "push", url: "", push_rtmp: "rtmp://relay/live/x", modes: ["push"], has_key: false, ...e };
  render(<ConfirmContext value={confirm}><MemoryRouter><Page initial={initial} /></MemoryRouter></ConfirmContext>);
  await act(async () => { for (let i = 0; i < 4; i++) await Promise.resolve(); });
}

describe("Settings › video input: the Sada Studio, no OBS", () => {
  beforeEach(() => {
    confirm = vi.fn<Confirm>();
    revoked.mockReset();
    for (const f of Object.values(api)) f.mockReset();
    api.studioDownload.mockResolvedValue({ version: "0.6.0", page: "https://github.com/x/releases/latest", assets: { windows: "https://dl/setup.exe", mac_arm64: null, mac_x64: null, linux: null } });
    api.studioDevices.mockResolvedValue({ devices: [{ id: 1, name: "PC salle", online: true, revoked: false }] });
    api.revokeStreamKey.mockResolvedValue({ ok: true, revoked: true });
  });
  afterEach(() => cleanup());

  it("hosted: the studio to download and link, no OBS address, no key, no camera", async () => {
    await monter({});
    expect(screen.getByText("onboarding.dlTitle")).toBeTruthy();
    expect(screen.getByText("PC salle")).toBeTruthy();
    expect(screen.queryByDisplayValue("rtmp://relay/live/x")).toBeNull();
    expect(screen.queryByText("settings.keyLeft")).toBeNull();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.getByRole("link", { name: "nav.devices" }).getAttribute("href")).toBe("/appareils");
  });

  it("an OBS key left from before is said, and revoked once confirmed", async () => {
    await monter({ has_key: true });
    expect(screen.getByText("settings.keyLeft")).toBeTruthy();
    confirm.mockResolvedValue(false);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "settings.keyRevoke" })); });
    expect(api.revokeStreamKey).not.toHaveBeenCalled();
    confirm.mockResolvedValue(true);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "settings.keyRevoke" })); });
    expect(api.revokeStreamKey).toHaveBeenCalledOnce();
    expect(revoked).toHaveBeenCalledOnce();
    expect(screen.queryByText("settings.keyLeft")).toBeNull();
    expect(screen.getByText("settings.keyRevoked")).toBeTruthy();
  });

  it("self-hosted: the studio first, the camera the server reads as the other choice", async () => {
    await monter({ modes: ["camera", "push"] });
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["settings.studioTab", "onboarding.cameraTitle"]);
    await act(async () => { fireEvent.click(screen.getByRole("tab", { name: "onboarding.cameraTitle" })); });
    expect(screen.getByText("onboarding.cameraUrl")).toBeTruthy();
    expect(screen.queryByText("onboarding.dlTitle")).toBeNull();
  });
});
