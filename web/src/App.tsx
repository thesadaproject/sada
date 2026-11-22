import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api, onUnauthorized, setCsrf, type Session } from "./api";
import Login from "./pages/Login";
import FirstPassword from "./pages/FirstPassword";
import MosquePicker from "./pages/MosquePicker";
import { setCurrentSession } from "./session";
import TopBar from "./TopBar";

// Each screen is its own chunk: signing in only downloads the shell, then the page being opened.
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Regie = lazy(() => import("./pages/Regie"));
const Devices = lazy(() => import("./pages/Devices"));
const Sermons = lazy(() => import("./pages/Sermons"));
const SermonDetail = lazy(() => import("./pages/SermonDetail"));
const Search = lazy(() => import("./pages/Search"));
const Habillage = lazy(() => import("./pages/Habillage"));
const Dars = lazy(() => import("./pages/Dars"));
const Clips = lazy(() => import("./pages/Clips"));
const ClipDetail = lazy(() => import("./pages/ClipDetail"));
const Publications = lazy(() => import("./pages/Publications"));
const Settings = lazy(() => import("./pages/Settings"));
const Users = lazy(() => import("./pages/Users"));
const Audit = lazy(() => import("./pages/Audit"));
const Onboarding = lazy(() => import("./pages/Onboarding"));
const PlatformSettings = lazy(() => import("./pages/PlatformSettings"));
const Tarawih = lazy(() => import("./pages/Tarawih"));
const TarawihNight = lazy(() => import("./pages/Tarawih").then((m) => ({ default: m.TarawihNight })));

export default function App() {
  const { t } = useTranslation();
  const [session, setSession] = useState<Session | null>(null);
  const [pret, setPret] = useState(false);
  const navigate = useNavigate();
  const demarragePropose = useRef(false);
  const { pathname } = useLocation();

  useEffect(() => {
    api.session()
      .then((s) => { setCurrentSession(s); setCsrf(s.csrf); setSession(s); })
      .catch(() => { setCurrentSession(null); setSession(null); })
      .finally(() => setPret(true));
    onUnauthorized(() => { setCurrentSession(null); setSession(null); });
  }, []);

  // First login: the three-step wizard is opened once, then everything lives in Settings.
  useEffect(() => {
    if (!session || demarragePropose.current) return;
    if (session.mosque?.needs_onboarding && session.user.permissions.includes("admin")) {
      demarragePropose.current = true;
      navigate("/demarrage", { replace: true });
    }
  }, [session, navigate]);

  if (!pret) return <p className="px-4 py-16 text-center text-muted">{t("common.loading")}</p>;
  if (!session) return <Login onLogin={(s) => { setCurrentSession(s); setCsrf(s.csrf); setSession(s); }} />;
  // Password chosen by an administrator: the person sets their own before anything else.
  if (session.user.must_change_password)
    return (
      <FirstPassword
        nom={session.user.name}
        onDone={() => api.session().then((s) => { setCurrentSession(s); setCsrf(s.csrf); setSession(s); })}
        onLogout={() => api.logout().catch(() => {}).finally(() => { setCurrentSession(null); setCsrf(""); setSession(null); })}
      />
    );

  // Signed in, but no mosque open yet (hosted mode, operator console): choose one first.
  const mosque = session.mosque;
  const adopter = (s: Session) => { setCurrentSession(s); setCsrf(s.csrf); setSession(s); };
  // The operator's platform page needs no mosque: it opens from the picker, with a way back.
  if (!mosque && pathname === "/platform/settings" && session.user.operator)
    return (
      <div className="min-h-dvh px-4 pt-6 pb-16">
        <div className="mx-auto mb-4 w-full max-w-[800px]">
          <button type="button" onClick={() => navigate("/", { replace: true })}
            className="cursor-pointer border-0 bg-transparent p-0 text-[0.9rem] font-semibold text-deep underline decoration-line underline-offset-4">
            {t("platform.back")}
          </button>
        </div>
        <Suspense fallback={<p className="py-16 text-center text-muted">{t("common.loading")}</p>}>
          <PlatformSettings />
        </Suspense>
      </div>
    );
  if (!mosque)
    return (
      <MosquePicker
        session={session}
        onPick={(s) => { demarragePropose.current = false; adopter(s); navigate("/", { replace: true }); }}
        onLogout={() => api.logout().catch(() => {}).finally(() => { setCurrentSession(null); setCsrf(""); setSession(null); })}
      />
    );
  const peutChanger = (session.mosques?.length ?? 0) > 1 || !!session.user.operator;
  const changerDeMosquee = () => api.leaveMosque().then(adopter);

  // Sign-out: the server clears the session, the login screen takes over without a reload.
  const deconnexion = async () => {
    await api.logout().catch(() => {});
    setCurrentSession(null);
    setCsrf("");
    setSession(null);
  };

  return (
    <div className="flex min-h-dvh flex-col">
      {session.support && (
        <div role="status" className="flex flex-wrap items-center justify-center gap-3 bg-gold px-4 py-1.5 text-[0.85rem] font-semibold text-night">
          <span>{t("picker.banner", { name: mosque.name })}</span>
          <button type="button" onClick={changerDeMosquee} className="cursor-pointer rounded border border-night/40 bg-transparent px-2 py-0.5 font-semibold text-night">{t("picker.leave")}</button>
        </div>
      )}
      <TopBar
        session={session}
        onLogout={deconnexion}
        onSwitchMosque={peutChanger && !session.support ? changerDeMosquee : undefined}
      />
      <main className="mx-auto w-full max-w-[1100px] flex-1 px-4 pt-6 pb-16">
        <Suspense fallback={<p className="py-16 text-center text-muted">{t("common.loading")}</p>}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/regie" element={<Regie />} />
          <Route path="/appareils" element={<Devices />} />
          <Route path="/khutbas" element={<Sermons />} />
          <Route path="/dars" element={<Dars />} />
          <Route path="/tarawih" element={<Tarawih />} />
          <Route path="/tarawih/:id" element={<TarawihNight />} />
          <Route path="/clips" element={<Clips />} />
          <Route path="/khutbas/:id" element={<SermonDetail />} />
          <Route path="/search" element={<Search />} />
          <Route path="/khutbas/:id/habillage" element={<Habillage />} />
          {/* Old address: already-shared links keep leading to the list. */}
          <Route path="/sermons" element={<Navigate to="/khutbas" replace />} />
          <Route path="/sermons/:id" element={<Navigate to="/khutbas" replace />} />
          <Route path="/clips/:id" element={<ClipDetail />} />
          <Route path="/publications" element={<Publications />} />
          <Route path="/demarrage" element={<Onboarding />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/platform/settings" element={<PlatformSettings />} />
          <Route path="/users" element={<Users />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="*" element={<p className="py-16 text-center text-muted">404</p>} />
        </Routes>
        </Suspense>
      </main>
      <footer className="p-6 text-center text-[0.8rem] text-muted">
        {t("app.name")} · {mosque.name}{session.version && <> · <span dir="ltr">{session.version}</span></>}
      </footer>
    </div>
  );
}
