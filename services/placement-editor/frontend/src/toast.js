// Tiny in-app toast bus. Any component calls `toast(msg, kind)` the same way it
// used to call `alert()` - no prop drilling - and <ToastHost/> (mounted once in
// App) renders + auto-dismisses. Replaces the browser alert() dialogs, which
// block the whole tab and read as a native popup rather than part of the tool.
let _seq = 0;
const listeners = new Set();

export function toast(message, kind = "info") {
  const t = { id: ++_seq, message: String(message), kind };
  listeners.forEach((fn) => fn(t));
  return t.id;
}

export function subscribeToasts(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
