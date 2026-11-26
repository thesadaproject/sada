// @vitest-environment happy-dom
import { act, cleanup, render, screen } from "@testing-library/react";
import { Provider } from "react-redux";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: "fr" } }),
}));
const api = vi.hoisted(() => ({ dashboard: vi.fn(), traitements: vi.fn(), liveCommande: vi.fn() }));
vi.mock("../api", () => ({ api, ApiError: class extends Error { status = 0; } }));

import type { Session } from "../api";
import { setCurrentSession } from "../session";
import { makeStore } from "../store";
import Dashboard from "./Dashboard";

const payload = {
  counts: { pending: 1, ready: 0, sermons: 2, dars: 0 }, recent: [], commands: [],
  live: { ok: true, state: "KHUTBA", scene: "khutba", stream_on: true, override: true, next_session: "13:30" },
  live_commands: ["start", "pause", "stop", "extend", "skip", "auto", "scene", "janaza", "tarawih", "next_reciter"]
    .map((key) => ({ key, destructive: key === "stop", choices: key === "extend" ? ["5"] : key === "scene" ? ["khutba"] : [] })),
};

async function monter(permissions: string[]) {
  setCurrentSession({ user: { permissions } } as unknown as Session);
  render(<Provider store={makeStore()}><MemoryRouter><Dashboard /></MemoryRouter></Provider>);
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

describe("Dashboard", () => {
  beforeEach(() => {
    api.dashboard.mockResolvedValue(payload);
    api.traitements.mockResolvedValue({ items: [], actif: false });
  });
  afterEach(() => { cleanup(); setCurrentSession(null); });

  it("shows the live read only: no command at all, the state and the scene on air", async () => {
    await monter(["live"]);
    expect(screen.getByText("dashboard.state.KHUTBA")).toBeTruthy();
    expect(screen.getByText("dashboard.choice.khutba")).toBeTruthy();
    expect(screen.getByText("13:30")).toBeTruthy();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
    expect(api.liveCommande).not.toHaveBeenCalled();
  });

  it("lays out today's programme: finished with its real times, live, next with its countdown", async () => {
    api.dashboard.mockResolvedValue({
      ...payload,
      live: {
        ok: true, state: "KHUTBA", scene: "khutba", stream_on: true, clock: "13:40:00", next_session: "20:45",
        day: [
          { planned: "12:30", status: "done", kind: "khutba", title: "", speaker: "", started: "12:31:10", ended: "13:02:44" },
          { planned: "13:30", status: "live", kind: "khutba", title: "", speaker: "", started: "13:31:04", ended: null },
          { planned: "20:45", status: "pending", kind: "dars", title: "Tafsir", speaker: "", started: null, ended: null },
        ],
      },
    });
    await monter(["live"]);
    expect(screen.getByText("12:31 – 13:02")).toBeTruthy();
    expect(screen.getAllByText("dashboard.onAirSince").length).toBeGreaterThan(0);
    expect(screen.getByText("dashboard.inDelay")).toBeTruthy();
    expect(screen.getByText("12:30")).toBeTruthy();
    expect(screen.getByText("dashboard.kind.dars")).toBeTruthy();
  });

  it("leads to the Régie for those who hold the live right only", async () => {
    await monter(["live"]);
    expect(screen.getByRole("link", { name: /dashboard\.openRegie/ }).getAttribute("href")).toBe("/regie");
    cleanup();
    await monter(["validate"]);
    expect(screen.queryByRole("link", { name: /dashboard\.openRegie/ })).toBeNull();
  });
});
