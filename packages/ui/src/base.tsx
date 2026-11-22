import { cloneElement, isValidElement, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { idOnglet, idPanneau } from "./onglets";
import type { Onglet } from "./onglets";
import type {
  FocusEvent as FocusReact,
  HTMLAttributes,
  KeyboardEvent as ToucheReact,
  MouseEvent as SourisReact,
  ReactElement,
  ReactNode,
  Ref,
} from "react";

/** Card accepts the panel attributes (role, id, aria-labelledby) without adding a wrapper:
 *  a tab panel must not introduce a box the layout did not have. */
export function Card({ children, className = "", ...reste }:
  { children: ReactNode; className?: string } & HTMLAttributes<HTMLElement>) {
  return (
    <section className={`rounded-[10px] border border-line bg-white p-4.5 ${className}`} {...reste}>{children}</section>
  );
}

export function Kicker({ children, sombre = false }: { children: ReactNode; sombre?: boolean }) {
  return (
    <p className={`m-0 mb-2 text-[0.75rem] font-semibold uppercase leading-none tracking-[0.12em] ${sombre ? "text-leaf" : "text-green"}`}>
      {children}
    </p>
  );
}

export function Title({ children, grand = false }: { children: ReactNode; grand?: boolean }) {
  return (
    <h2 className={`m-0 mb-2 font-serif font-normal leading-[1.15] text-deeper ${grand ? "text-[2.1rem]" : "text-[1.55rem]"}`}>
      {children}
    </h2>
  );
}

export function Btn({
  children,
  variante = "plein",
  className = "",
  ...reste
}: { children: ReactNode; variante?: "plein" | "ghost" | "leaf" | "danger" | "dangerGhost" | "light"; ref?: Ref<HTMLButtonElement> } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const styles = {
    plein: "border-deep bg-deep text-white hover:bg-deeper",
    ghost: "border-deep bg-transparent text-deep hover:bg-paper-2",
    leaf: "border-leaf bg-leaf text-night hover:bg-leaf-2",
    danger: "border-live bg-live text-white hover:bg-[#7f2122]",
    // Secondary destructive action: visible without stealing the main action's place.
    dangerGhost: "border-live/50 bg-transparent text-[#7f2122] hover:bg-err-bg",
    light: "border-white/25 bg-white/10 text-white hover:bg-white/18",
  }[variante];
  // Un bouton inactif se lit comme tel : neutre et plat, pas une couleur d'action délavée.
  const apparence = reste.disabled
    ? "cursor-not-allowed border-line bg-paper-2 text-muted"
    : `cursor-pointer ${styles}`;
  // Au doigt (téléphone, tablette), jamais moins de 44 px, même quand l'appelant compacte le bouton.
  return (
    <button
      type="button"          /* default inside a form; callers pass type="submit" where needed */
      className={`inline-flex min-h-11 items-center justify-center gap-1.5 rounded-[9px] border px-4 py-2.5 font-semibold ${apparence} ${className} max-md:min-h-11! pointer-coarse:min-h-11!`}
      {...reste}
    >
      {children}
    </button>
  );
}

const PILLS: Record<string, string> = {
  a_valider: "bg-warn-bg text-warn",
  valide: "bg-paper-2 text-deep",
  rejete: "bg-err-bg text-[#7a1f20]",
  publie: "bg-deep text-white",
  // Runs after the live: waiting, running, ready, failed.
  attente: "bg-paper-2 text-muted",
  en_cours: "bg-warn-bg text-warn",
  termine: "bg-[#f3ecdc] text-green",
  echec: "bg-err-bg text-[#7a1f20]",
};

export function Pill({ statut, label }: { statut: string; label: string }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-[0.8rem] font-bold ${PILLS[statut] ?? "bg-[#efe8d8] text-muted"}`}>
      {label}
    </span>
  );
}

/* ---------------------------------------------------------------------------
 * Onglets — comportements repris de la bibliothèque vercel-labs/ui (onglets,
 * sélecteurs segmentés), écrits ici sans dépendance : rôles tablist/tab, un
 * seul onglet atteint au Tab (roving tabindex), flèches gauche/droite,
 * Début/Fin, et panneau relié à son onglet par aria-controls/aria-labelledby.
 * ------------------------------------------------------------------------- */

/** Clavier et roving tabindex communs à Tabs et Segmented. L'onglet retenu est
 *  le seul arrêt de tabulation ; les flèches changent d'onglet et posent le
 *  focus dessus (activation automatique, le panneau étant peu coûteux). */
function useOnglets(items: Onglet[], valeur: string, onChange: (cle: string) => void) {
  const boutons = useRef<Record<string, HTMLButtonElement | null>>({});
  const ouverts = items.filter((it) => !it.eteint);
  const choisi = ouverts.some((it) => it.cle === valeur) ? valeur : (ouverts[0]?.cle ?? "");
  const aller = (cle: string) => { onChange(cle); boutons.current[cle]?.focus(); };

  const clavier = (e: ToucheReact<HTMLButtonElement>) => {
    if (!ouverts.length) return;
    // En écriture de droite à gauche, la flèche de gauche avance.
    const pas = getComputedStyle(e.currentTarget).direction === "rtl" ? -1 : 1;
    const i = Math.max(0, ouverts.findIndex((it) => it.cle === choisi));
    let cible: Onglet | undefined;
    if (e.key === "ArrowRight") cible = ouverts[(i + pas + ouverts.length) % ouverts.length];
    else if (e.key === "ArrowLeft") cible = ouverts[(i - pas + ouverts.length) % ouverts.length];
    else if (e.key === "Home") cible = ouverts[0];
    else if (e.key === "End") cible = ouverts[ouverts.length - 1];
    else return;
    e.preventDefault();          /* la flèche ne fait pas défiler la page */
    if (cible) aller(cible.cle);
  };

  return {
    choisi,
    clavier,
    tabIndex: (it: Onglet) => (it.eteint ? -1 : it.cle === choisi ? 0 : -1),
    ref: (cle: string) => (el: HTMLButtonElement | null) => { boutons.current[cle] = el; },
  };
}

/** Top-level tabs: separate pills, the active one filled in deep green (.tabs in the back-office).
 *  `base` (optional) links each tab to the panel that follows it: the panel carries
 *  `role="tabpanel"`, `id={idPanneau(base, cle)}` and `aria-labelledby={idOnglet(base, cle)}`. */
export function Tabs({
  items,
  valeur,
  onChange,
  base,
  label,
}: {
  items: Onglet[];
  valeur: string;
  onChange: (cle: string) => void;
  base?: string;
  label?: string;
}) {
  const { choisi, clavier, tabIndex, ref } = useOnglets(items, valeur, onChange);
  return (
    // Téléphone : une seule ligne qui défile dans son propre conteneur, jamais la page.
    <div role="tablist" aria-label={label}
      className="mb-3.5 flex flex-wrap gap-2 max-md:flex-nowrap max-md:overflow-x-auto max-md:[scrollbar-width:none]">
      {items.map((it) => (
        <button
          key={it.cle}
          type="button"          /* a tab never submits the form around it */
          role="tab"
          id={base ? idOnglet(base, it.cle) : undefined}
          aria-selected={it.cle === choisi}
          aria-controls={base ? idPanneau(base, it.cle) : undefined}
          tabIndex={tabIndex(it)}
          ref={ref(it.cle)}
          onKeyDown={clavier}
          onClick={() => onChange(it.cle)}
          disabled={it.eteint}
          className={`inline-flex min-h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-3.5 py-1.5 text-[0.93rem] font-semibold max-md:min-h-11 pointer-coarse:min-h-11 ${
            it.eteint ? "cursor-not-allowed border-line bg-white/60 text-muted/60" : "cursor-pointer"
          } ${
            valeur === it.cle
              ? "border-deep bg-deep text-white"
              : "border-line bg-white text-deep hover:border-leaf hover:bg-paper-2"
          }`}
        >
          {it.label}
          {it.compte !== undefined && (
            <span className={`rounded-full px-1.5 text-[0.78rem] ${valeur === it.cle ? "bg-white/20" : "bg-paper-2 text-muted"}`}>
              {it.compte}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

/** Segmented selector: a single block, for the sub-tabs of one screen.
 *  `compte` (optional) shows a small total next to the label.
 *  Même clavier que Tabs. `base` relie l'onglet à son panneau quand il y en a un. */
export function Segmented({
  items,
  valeur,
  onChange,
  base,
  label,
}: {
  items: Onglet[];
  valeur: string;
  onChange: (cle: string) => void;
  base?: string;
  label?: string;
}) {
  const { choisi, clavier, tabIndex, ref } = useOnglets(items, valeur, onChange);
  return (
    <div role="tablist" aria-label={label}
      className="mb-3 inline-flex max-w-full flex-wrap gap-0.5 rounded-[9px] border border-line bg-paper-2 p-[3px] max-md:flex max-md:w-fit max-md:flex-nowrap max-md:overflow-x-auto max-md:[scrollbar-width:none]">
      {items.map((it) => (
        <button
          key={it.cle}
          type="button"          /* a tab never submits the form around it */
          role="tab"
          id={base ? idOnglet(base, it.cle) : undefined}
          aria-selected={it.cle === choisi}
          aria-controls={base ? idPanneau(base, it.cle) : undefined}
          tabIndex={tabIndex(it)}
          ref={ref(it.cle)}
          onKeyDown={clavier}
          onClick={() => onChange(it.cle)}
          disabled={it.eteint}
          className={`inline-flex min-h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-[7px] border-0 px-3.5 py-1 text-[0.88rem] font-semibold max-md:min-h-11 max-md:px-3 pointer-coarse:min-h-11 ${
            it.eteint ? "cursor-not-allowed text-muted/60" : "cursor-pointer"
          } ${
            valeur === it.cle
              ? "bg-white text-deeper shadow-[0_1px_2px_rgba(23,38,28,0.14),inset_0_-2px_0_var(--color-leaf)]"
              : "bg-transparent text-muted hover:bg-white/60 hover:text-ink"
          }`}
        >
          {it.label}
          {it.compte !== undefined && (
            <span className={`rounded-full px-1.5 text-[0.76rem] tabular-nums ${valeur === it.cle ? "bg-paper-2 text-deep" : "bg-white/70 text-muted"}`}>
              {it.compte}
            </span>
          )}
          {it.eteint && <span className="inline-block size-[7px] rounded-full border-[1.5px] border-muted" />}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Info-bulle — comme celle de vercel-labs/ui : elle précise son déclencheur au
 * survol ET au focus clavier, Échap la referme (le focus reste où il est), et
 * le texte reste attaché par aria-describedby même quand rien n'est affiché.
 * Elle reste survolable (WCAG 1.4.13) : le pointeur peut passer du déclencheur
 * à la bulle sans qu'elle se ferme.
 * ------------------------------------------------------------------------- */

/** Courte précision posée sur un élément (bouton, nom…). Un seul enfant, qui
 *  reçoit aria-describedby ; `actif={false}` ne rend que l'enfant. Si le texte
 *  répète le nom accessible de l'enfant (aria-label identique), la bulle reste
 *  purement visuelle : elle ne s'ajoute pas en description, on lirait deux fois la même chose. */
export function Bulle({ texte, children, actif = true, masque = false, place = "bas", aligne = "debut" }: {
  texte: string;
  children: ReactNode;
  actif?: boolean;
  /** Cache la bulle sans changer le DOM (le déclencheur garde son focus), ex. pendant qu'un menu est ouvert. */
  masque?: boolean;
  place?: "bas" | "haut";
  /** Bord de l'enfant sur lequel la bulle s'aligne : `fin` évite de déborder d'un conteneur à droite. */
  aligne?: "debut" | "fin";
}) {
  const id = useId();
  const [ouvert, setOuvert] = useState(false);
  // Échap la referme : elle ne revient qu'après une nouvelle entrée du pointeur
  // (mouseenter) ou du focus, pas toute seule.
  const montre = actif && ouvert && !masque;

  // Échap ferme la bulle où que soit le focus (WCAG 1.4.13 : fermable sans bouger le pointeur).
  useEffect(() => {
    if (!montre) return;
    const touche = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); setOuvert(false); }
    };
    document.addEventListener("keydown", touche, true);
    return () => document.removeEventListener("keydown", touche, true);
  }, [montre]);

  const enfant = isValidElement(children) ? (children as ReactElement<Record<string, any>>) : null;
  const avant = (enfant?.props ?? {}) as Record<string, any>;

  if (!actif) return <>{children}</>;

  const memeNom = avant["aria-label"] === texte;
  const declencheur = enfant
    ? cloneElement(enfant, {
        "aria-describedby": memeNom ? avant["aria-describedby"] : [avant["aria-describedby"], id].filter(Boolean).join(" ") || undefined,
        // Au clavier seulement : un clic à la souris donne aussi le focus, la bulle ne doit pas y rester collée.
        onFocus: (e: FocusReact) => { avant.onFocus?.(e); if (e.currentTarget.matches(":focus-visible")) setOuvert(true); },
        onBlur: (e: FocusReact) => { avant.onBlur?.(e); setOuvert(false); },
      })
    : children;

  // Les événements du pointeur sont sur l'enveloppe : la bulle en fait partie, donc la survoler
  // garde le déclencheur « survolé ». Le rembourrage (pt-1.5 / pb-1.5) comble l'espace entre les deux.
  return (
    <span className="relative inline-flex min-w-0"
      onMouseEnter={() => setOuvert(true)} onMouseLeave={() => setOuvert(false)}>
      {declencheur}
      <span
        role="tooltip"
        id={id}
        aria-hidden={memeNom || undefined}
        className={`absolute z-40 w-max max-w-[16rem] ${aligne === "fin" ? "end-0" : "start-0"} ${
          place === "haut" ? "bottom-full pb-1.5" : "top-full pt-1.5"
        } ${montre ? "" : "hidden"}`}
      >
        <span className="block rounded-[6px] bg-night px-2 py-1 text-[0.78rem] leading-snug font-normal text-paper shadow-[0_6px_18px_rgba(10,16,12,0.3)]">
          {texte}
        </span>
      </span>
    </span>
  );
}

/* ---------------------------------------------------------------------------
 * Modale — l'élément natif <dialog> ouvert par showModal() : le navigateur
 * rend la page inerte, garde le focus dans la boîte, gère Échap et rend le
 * focus au déclencheur. Le clic à l'extérieur ferme (closedby="any").
 * ------------------------------------------------------------------------- */

/** Modale du site : voile sombre (::backdrop), boîte centrée (le navigateur borne déjà sa taille à la fenêtre). `boite` reprend les classes de la
 *  page, donc rien ne change visuellement. `onFermer` est appelé à toute fermeture venue de
 *  l'utilisateur (Échap, clic à l'extérieur) ; un bouton de la boîte appelle lui-même la sienne. */
export function Dialogue({ label, onFermer, boite = "", children }: {
  label: string;
  onFermer: () => void;
  boite?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  // La fermeture change à chaque rendu : on la lit par référence, pas par dépendance.
  const fermer = useRef(onFermer);
  useEffect(() => { fermer.current = onFermer; }, [onFermer]);

  useLayoutEffect(() => {
    const d = ref.current;
    if (!d) return;
    const surFermeture = () => fermer.current();
    d.addEventListener("close", surFermeture);
    if (!d.open) d.showModal();
    return () => {
      // Démontage (ou double passage de StrictMode) : pas de rappel de fermeture.
      d.removeEventListener("close", surFermeture);
      if (d.open) d.close();
    };
  }, []);

  // Safari ne connaît pas closedby : même effet à la main. Le <dialog> est lui-même la cible d'un
  // clic sur le voile ; on compare donc la position du pointeur à la boîte.
  const dehors = (e: SourisReact<HTMLDialogElement>) => {
    if (e.target !== e.currentTarget || "closedBy" in HTMLDialogElement.prototype) return;
    const r = e.currentTarget.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) e.currentTarget.close();
  };

  return (
    <dialog
      ref={ref}
      aria-label={label}
      {...({ closedby: "any" } as object)}
      onClick={dehors}
      className={`m-auto overscroll-contain text-ink backdrop:overflow-hidden backdrop:overscroll-contain backdrop:bg-night/50 not-open:hidden ${boite}`}
    >
      {children}
    </dialog>
  );
}

export function Field({ label, aide, children, className = "" }:
  { label: string; aide?: string; children: ReactNode; className?: string }) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1 block text-[0.9rem] font-semibold">{label}</span>
      {children}
      {aide && <span className="mt-1 block text-[0.82rem] text-muted">{aide}</span>}
    </label>
  );
}

/** Table headers and cells: a single horizontal padding (8 px) so titles and values line up,
 *  and no border under the last row (it would double the card's). */
export const thClass =
  "border-b border-line px-2 py-2 text-left text-[0.75rem] font-semibold uppercase tracking-[0.08em] text-muted";
export const tdClass = "border-b border-line px-2 py-2.5 align-middle [tr:last-child_&]:border-b-0";

/** Simple table, no sortable header: the last row keeps no border. */
export function Table({ entetes, children }: { entetes: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
    <table className="w-full border-collapse text-[0.95rem]">
      <thead>
        <tr>
          {entetes.map((h) => (
            <th key={h} scope="col" className={thClass}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
    </div>
  );
}

/** Lien ou petit bouton texte placé seul (élément de grille ou de rangée flex) : au doigt, une zone
 *  de toucher d'au moins 44 px de haut, sans changer l'apparence à la souris. */
export const toucher =
  "max-md:inline-flex max-md:min-h-11 max-md:items-center pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center";
/** Lien au fil d'une phrase : le rembourrage vertical agrandit la zone sans déplacer la ligne. */
export const toucherEnLigne = "max-md:py-[13px] pointer-coarse:py-[13px]";

export const inputClass =
  "w-full rounded-lg border border-[#cfc6b0] bg-white px-3 py-2.5 text-ink read-only:cursor-default read-only:bg-paper-2 read-only:text-muted disabled:bg-paper-2 disabled:text-muted";

/** Drop-down menu (ARIA « menu button »): the trigger opens a list of links or actions.
 *  Arrow keys move between items, Escape closes and gives the focus back to the trigger, a click
 *  outside or on an item closes it. Items carry `role="menuitem"` (or `menuitemradio`). */
export function Deroulant({ bouton, label, children, aligne = "debut", classeBouton = "", classeMenu = "" }: {
  bouton: ReactNode; label?: string; children: ReactNode;
  aligne?: "debut" | "fin"; classeBouton?: string; classeMenu?: string;
}) {
  const [ouvert, setOuvert] = useState(false);
  const racine = useRef<HTMLDivElement>(null);
  const declencheur = useRef<HTMLButtonElement>(null);
  const id = useId();
  const items = () =>
    Array.from(racine.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? []);

  useEffect(() => {
    if (!ouvert) return;
    const dehors = (e: PointerEvent) => {
      if (!racine.current?.contains(e.target as Node)) setOuvert(false);
    };
    document.addEventListener("pointerdown", dehors);
    return () => document.removeEventListener("pointerdown", dehors);
  }, [ouvert]);

  const ouvrir = (premier: boolean) => {
    setOuvert(true);
    window.requestAnimationFrame(() => {
      const liste = items();
      (premier ? liste[0] : liste[liste.length - 1])?.focus();
    });
  };

  const surTouche = (e: ToucheReact<HTMLDivElement>) => {
    if (e.key === "Escape" && ouvert) {
      e.preventDefault();
      setOuvert(false);
      declencheur.current?.focus();
      return;
    }
    if (e.key === "Tab" && ouvert) { setOuvert(false); return; }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) return;
    if (!ouvert) {
      if (e.target === declencheur.current && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
        e.preventDefault();
        ouvrir(e.key === "ArrowDown");
      }
      return;
    }
    e.preventDefault();
    const liste = items();
    const i = liste.indexOf(document.activeElement as HTMLElement);
    const n = liste.length;
    const suivant = e.key === "Home" ? 0 : e.key === "End" ? n - 1
      : e.key === "ArrowDown" ? (i + 1) % n : (i - 1 + n) % n;
    liste[suivant]?.focus();
  };

  return (
    <div ref={racine} className="relative" onKeyDown={surTouche}>
      <Bulle texte={label ?? ""} actif={!!label} masque={ouvert} aligne={aligne}>
        <button
          ref={declencheur}
          type="button"
          aria-haspopup="menu"
          aria-expanded={ouvert}
          aria-controls={id}
          aria-label={label}
          onClick={() => setOuvert((o) => !o)}
          className={`cursor-pointer ${classeBouton}`}
        >
          {bouton}
        </button>
      </Bulle>
      <div
        id={id}
        role="menu"
        hidden={!ouvert}
        onClick={(e) => {
          if ((e.target as HTMLElement).closest('[role^="menuitem"]')) setOuvert(false);
        }}
        className={`absolute top-[calc(100%+8px)] z-50 min-w-[13rem] rounded-xl border border-white/10 bg-deeper p-1.5 text-night-ink shadow-[0_18px_40px_rgba(0,0,0,0.35)] ${
          aligne === "fin" ? "end-0" : "start-0"
        } ${classeMenu}`}
      >
        {children}
      </div>
    </div>
  );
}

/** Classes of one item of a `Deroulant` (link or button): base, then current page or not. */
export const itemMenuBase =
  "flex w-full cursor-pointer items-center justify-between gap-3 rounded-lg border-0 px-3 py-2 text-start text-[0.95rem] no-underline outline-none transition-colors focus-visible:bg-leaf/20 max-md:min-h-11 pointer-coarse:min-h-11";
export const itemMenuActif = "bg-leaf/15 text-white";
export const itemMenuRepos = "bg-transparent text-night-link hover:bg-leaf/15 hover:text-white";
