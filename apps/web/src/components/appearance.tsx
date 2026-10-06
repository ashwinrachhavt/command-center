"use client";

import { useEffect, useSyncExternalStore } from "react";
import { ThemeProvider, useTheme } from "next-themes";
import { Check, Palette } from "lucide-react";
import { ThemeSwitcher } from "@/components/kibo-ui/theme-switcher";
import { Button } from "@/components/ui/button";
import { AnimatedIcon } from "@/components/ui/animated-icon";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const palettes = [
  { id: "graphite", name: "Graphite", color: "#727782" },
  { id: "teal", name: "Teal", color: "#188879" },
  { id: "blue", name: "Blue", color: "#436fe4" },
  { id: "violet", name: "Violet", color: "#8958d8" },
] as const;
const storageKey = "command-center:palette";

function applyPalette(palette: string) {
  const root = document.documentElement;
  if (root.dataset.palette === palette) return;

  const style = document.createElement("style");
  style.textContent = "*,*::before,*::after{transition:none !important}";
  document.head.append(style);
  root.dataset.palette = palette;
  void root.offsetHeight;
  requestAnimationFrame(() => requestAnimationFrame(() => style.remove()));
}

function currentPalette() {
  try {
    const value = localStorage.getItem(storageKey);
    return palettes.some((palette) => palette.id === value)
      ? value!
      : "graphite";
  } catch {
    return document.documentElement.dataset.palette ?? "graphite";
  }
}

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener("palette-change", callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener("palette-change", callback);
  };
}

export function AppearanceProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const palette = useSyncExternalStore(
    subscribe,
    currentPalette,
    () => "graphite",
  );
  useEffect(() => {
    applyPalette(palette);
  }, [palette]);
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      storageKey="command-center:theme"
      disableTransitionOnChange
    >
      {children}
    </ThemeProvider>
  );
}

export function Appearance() {
  const { theme, setTheme } = useTheme();
  const palette = useSyncExternalStore(
    subscribe,
    currentPalette,
    () => "graphite",
  );
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="Appearance">
          <Palette />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-5">
        <h2 className="text-sm font-medium">Appearance</h2>
        <div className="mt-5 flex items-center justify-between gap-3">
          <span className="text-xs text-muted-foreground">Theme</span>
          <ThemeSwitcher
            value={theme === "light" || theme === "dark" ? theme : "system"}
            onChange={setTheme}
          />
        </div>
        <fieldset className="mt-5">
          <legend className="mb-3 text-xs text-muted-foreground">
            Accent color
          </legend>
          <div className="grid grid-cols-4 gap-2">
            {palettes.map((option) => (
              <Button
                key={option.id}
                variant="ghost"
                aria-pressed={palette === option.id}
                className={cn(
                  "h-auto flex-col gap-2 px-1 py-2 text-[11px]",
                  palette === option.id && "bg-accent",
                )}
                onClick={() => {
                  applyPalette(option.id);
                  try {
                    localStorage.setItem(storageKey, option.id);
                  } catch {
                    /* The current session still gets the selected palette. */
                  }
                  window.dispatchEvent(new Event("palette-change"));
                }}
              >
                <span
                  className="flex size-7 items-center justify-center rounded-full text-white"
                  style={{ background: option.color }}
                >
                  <AnimatedIcon
                    state={palette === option.id}
                    className="size-3.5"
                  >
                    {palette === option.id && <Check />}
                  </AnimatedIcon>
                </span>
                {option.name}
              </Button>
            ))}
          </div>
        </fieldset>
        <p className="mt-4 text-[11px] text-muted-foreground">
          Saved for this browser.
        </p>
      </PopoverContent>
    </Popover>
  );
}
