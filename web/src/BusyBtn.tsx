import type { ComponentProps } from "react";
import { Btn } from "@sada/ui";

/** A button whose own action is in flight: it keeps its colours and its place (no grey `disabled`
 *  flash), shows a small spinner, announces `aria-busy` and ignores clicks until it settles. */
export function BusyBtn({ busy = false, onClick, children, className = "", ...reste }:
  ComponentProps<typeof Btn> & { busy?: boolean }) {
  return (
    <Btn
      {...reste}
      className={`${busy ? "cursor-wait!" : ""} ${className}`}
      aria-busy={busy || undefined}
      aria-disabled={busy || reste["aria-disabled"] || undefined}
      onClick={busy ? undefined : onClick}
    >
      {busy && (
        <span aria-hidden="true" className="inline-block size-3.5 shrink-0 animate-spin rounded-full border-2 border-current border-r-transparent" />
      )}
      {children}
    </Btn>
  );
}
