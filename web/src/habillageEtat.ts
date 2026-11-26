import type { Habillage } from "./api";

/** Merge of two reads of a branding state: the preview never steps back. `preview_v` is the mtime of
 *  `apercu.jpg`, which the server only ever rewrites (never deletes), so a lower value can only come
 *  from a read that left before the last "Update the preview": the newer frame is kept.
 *  `video_v` is not held this way: it legitimately falls to 0 while a new rendering replaces the file. */
export function previewMonotone(prev: Habillage | null, next: Habillage): Habillage {
  if (prev && next.preview_v < prev.preview_v) {
    return { ...next, preview_v: prev.preview_v, preview_ready: prev.preview_ready };
  }
  return next;
}
