import { useCallback, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Btn, Dialogue } from "@sada/ui";
import { ConfirmContext, type Confirm, type ConfirmOptions } from "./confirmContext";

/** Replaces window.confirm(): `if (!(await confirm({ message }))) return;`. The question opens in
 *  the shared native dialog, with the focus on Cancel (the safe choice), so a stray Enter or
 *  Space never runs a destructive action. Escape and a click outside also cancel. */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [pending, setPending] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((ok: boolean) => void) | null>(null);

  const answer = useCallback((ok: boolean) => {
    resolver.current?.(ok);
    resolver.current = null;
    setPending(null);
  }, []);

  const confirm = useCallback<Confirm>((options) => {
    resolver.current?.(false);   // a second question replaces the first, which counts as refused
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
      setPending(options);
    });
  }, []);

  return (
    <ConfirmContext value={confirm}>
      {children}
      {pending && (
        <Dialogue label={t("common.confirmTitle")} onFermer={() => answer(false)}
          boite="grid w-[min(460px,calc(100dvw-2rem))] gap-4 rounded-[10px] border border-line bg-white p-5">
          <p className="m-0 text-[1rem] leading-[1.5]">{pending.message}</p>
          <div className="flex flex-wrap justify-end gap-2">
            {/* Cancel takes the focus: showModal() focuses the first focusable element. */}
            <Btn variante="ghost" onClick={() => answer(false)}>{t("common.cancel")}</Btn>
            <Btn variante={pending.danger === false ? "plein" : "danger"} onClick={() => answer(true)}>
              {pending.action ?? t("common.confirm")}
            </Btn>
          </div>
        </Dialogue>
      )}
    </ConfirmContext>
  );
}
