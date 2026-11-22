# @sada/ui

Design system Sada : charte (nuit / or / ivoire, polices, chiffres tabulaires), accent par mosquée,
logo صدى, composants de la console et composants des horaires de prière.

- Charte : `import "@sada/ui/theme.css"` dans la feuille Tailwind 4 de l'appli, et
  `@source "<chemin>/packages/ui/src";` pour que Tailwind y trouve ses classes.
- Accent par mosquée : `<Surface accent="#7b1e3a">` pose `--accent` et `--accent-ink` (encre calculée par
  contraste WCAG, voir `accent.ts`). Sans accent : l'or Sada.
- Horaires (purs, pilotés par props, mobile d'abord, hauteur naturelle, `tv` en option) :
  `PrayerRow`/`PrayerList`, `Clock`, `Countdown`, `MonthTable`, `ErrorPage`, `Surface`.
  Chourouk (`chourouk`) n'a que son heure (ni adhan ni iqama) et n'est jamais la cible du compte à rebours
  (`cibleCompteARebours`).
- Logo : `<Logo couleur="or|encre|courant" />`, tracé de `assets/logo/sada-mark-or.svg`
  (`node scripts/gen-logo.mjs` régénère `src/logo-data.ts`). Jamais `static/emblem.svg`.

## Développement

```
npm ci                                  # à la racine du dépôt
npm -w @sada/ui run storybook           # http://localhost:6006
npm -w @sada/ui run test                # tests unitaires (vitest)
npm -w @sada/ui run build-storybook && npm -w @sada/ui run visuel
```

`visuel` ouvre chaque story à sa taille (390 px, ou 1920x1080 si le nom commence par TV), vérifie
l'absence d'erreur console et de débordement horizontal, et écrit des PNG densité 2. Avec
`-- --compare <dossier>` il compare aux captures de référence (poste de développement seulement :
le rendu des polices diffère d'une machine à l'autre, la CI ne compare donc pas les pixels).
Storybook n'est pas dans le build de production.
