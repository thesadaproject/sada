// Composants de base de la console (extraits de web/src/ui.tsx, rendu inchangé).
export * from "./base";
export * from "./onglets";
// Identité.
export { Logo } from "./Logo";
export { accentStyle, contraste, encreSur, luminance } from "./accent";
// Horaires de prière : purs, pilotés par props.
export { Surface } from "./horaires/Surface";
export { PrayerRow, PrayerList, cibleCompteARebours } from "./horaires/PrayerRow";
export type { PrayerRowProps } from "./horaires/PrayerRow";
export { Clock } from "./horaires/Clock";
export { Countdown, formatRestant } from "./horaires/Countdown";
export { MonthTable } from "./horaires/MonthTable";
export type { MonthColumn, MonthDay } from "./horaires/MonthTable";
export { ErrorPage } from "./horaires/ErrorPage";
