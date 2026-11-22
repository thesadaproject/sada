import { createContext, use } from "react";

/** What a confirmation shows: the question, and optionally the verb of the action itself. */
export type ConfirmOptions = { message: string; action?: string; danger?: boolean };
export type Confirm = (options: ConfirmOptions) => Promise<boolean>;

export const ConfirmContext = createContext<Confirm | null>(null);

/** `if (!(await confirm({ message }))) return;` — the replacement of window.confirm(). */
export function useConfirm(): Confirm {
  const confirm = use(ConfirmContext);
  if (!confirm) throw new Error("useConfirm needs a <ConfirmProvider>");
  return confirm;
}
