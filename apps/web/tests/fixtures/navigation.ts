import { useSyncExternalStore } from "react";

const subscribe = (callback: () => void) => {
  window.addEventListener("popstate", callback);
  return () => window.removeEventListener("popstate", callback);
};
export function usePathname() {
  return useSyncExternalStore(subscribe, () => location.pathname);
}
export function useSearchParams() {
  const search = useSyncExternalStore(subscribe, () => location.search);
  return new URLSearchParams(search);
}
export function installNavigation() {
  for (const method of ["pushState", "replaceState"] as const) {
    const original = history[method].bind(history);
    history[method] = (...args) => {
      original(...args);
      window.dispatchEvent(new PopStateEvent("popstate"));
    };
  }
}

export function useRouter() {
  return {
    push: (href: string) => window.history.pushState(null, "", href),
    replace: (href: string) => window.history.replaceState(null, "", href),
  };
}
