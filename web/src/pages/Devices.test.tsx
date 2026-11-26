// @vitest-environment happy-dom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: "fr" } }),
}));
const api = vi.hoisted(() => ({
  studioDevices: vi.fn(),
  studioRename: vi.fn(),
  studioAlertPrefs: vi.fn(),
  studioRevoke: vi.fn(),
  studioRotate: vi.fn(),
  studioTakeover: vi.fn(),
  studioPair: vi.fn(),
}));
vi.mock("../api", () => ({ api }));

import { ConfirmContext } from "../confirmContext";
import Devices from "./Devices";

function differe<T>() {
  let resolve!: (v: T) => void, reject!: (e: unknown) => void;
  const promise = new Promise<T>((ok, ko) => { resolve = ok; reject = ko; });
  return { promise, resolve, reject };
}

const appareil = (id: number, name: string) => ({
  id, name, online: false, revoked: false, revoked_at: null, created_at: "2026-01-01", created_by_name: "",
  last_seen_at: null, app_version: "", state: "", camera: null, microphone: null, bitrate_kbps: null,
  health: {}, held: false, rotation_pending: false,
});
const donnees = (champs: { name?: string; subscribed?: boolean } = {}) => ({
  devices: [appareil(1, champs.name ?? "Salle")], incidents: [], publisher: null,
  order: { command: "standby", source: null, code: "", current: null, next: null },
  slots: [], settings: { start_margin_s: 600 }, can_takeover: false,
  mail: { configured: true, email: "a@b.c", subscribed: champs.subscribed ?? false },
  mosque: { name: "M", slug: "m" },
});

async function monter() {
  render(<ConfirmContext value={async () => true}><Devices /></ConfirmContext>);
  await act(async () => { await Promise.resolve(); });
}

describe("Devices", () => {
  beforeEach(() => { for (const f of Object.values(api)) f.mockReset(); });
  afterEach(cleanup);

  it("1a: a failed rename does not take back the alert box ticked meanwhile", async () => {
    api.studioDevices.mockResolvedValue(donnees());
    await monter();
    const renommage = differe<{ message?: string }>(), abonnement = differe<{ message?: string }>();
    api.studioRename.mockReturnValueOnce(renommage.promise);
    api.studioAlertPrefs.mockReturnValueOnce(abonnement.promise);

    fireEvent.click(screen.getByText("devices.rename"));
    fireEvent.change(screen.getByDisplayValue("Salle"), { target: { value: "Nouveau nom" } });
    fireEvent.submit(screen.getByDisplayValue("Nouveau nom").closest("form")!);
    expect(screen.getByText("Nouveau nom")).toBeTruthy();                       // shown at once

    const boite = screen.getByRole("checkbox") as HTMLInputElement;
    fireEvent.click(boite);
    expect(boite.checked).toBe(true);                                            // shown at once

    // The server still has the old state while the subscription is in flight.
    await act(async () => { renommage.reject(new Error("nom refusé")); await Promise.resolve(); });
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true);   // B not taken back
    expect(screen.queryByText("Nouveau nom")).toBeNull();                       // A reverted
    // 1b: the form opens again with what was typed, and the message says why.
    expect((screen.getByDisplayValue("Nouveau nom") as HTMLInputElement).form).toBeTruthy();
    expect(screen.getByText("nom refusé")).toBeTruthy();

    api.studioDevices.mockResolvedValue(donnees({ subscribed: true }));
    await act(async () => { abonnement.resolve({ message: "ok" }); await Promise.resolve(); });
    expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
  });

  it("a successful rename closes the form and keeps the new name", async () => {
    api.studioDevices.mockResolvedValue(donnees());
    await monter();
    api.studioRename.mockResolvedValueOnce({ message: "renommé" });
    fireEvent.click(screen.getByText("devices.rename"));
    fireEvent.change(screen.getByDisplayValue("Salle"), { target: { value: "Oratoire" } });
    api.studioDevices.mockResolvedValue(donnees({ name: "Oratoire" }));
    await act(async () => { fireEvent.submit(screen.getByDisplayValue("Oratoire").closest("form")!); await Promise.resolve(); });
    expect(screen.queryByDisplayValue("Oratoire")).toBeNull();
    expect(screen.getByText("Oratoire")).toBeTruthy();
    expect(screen.getByText("renommé")).toBeTruthy();
  });
});
