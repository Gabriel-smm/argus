"use client";

import { useEffect, useId, useRef, useState, type FC } from "react";
import { useAui, useAuiState } from "@assistant-ui/react";
import { CheckIcon, GlobeIcon } from "lucide-react";

import { LANGUAGES, useLanguage, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** Globe button with the current language; opens a short list to pick another. */
export const LanguageMenu: FC<{ className?: string }> = ({ className }) => {
  const { language, t } = useT();
  const setLanguage = useLanguage((s) => s.setLanguage);
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const listId = useId();
  const current = LANGUAGES.find((entry) => entry.code === language) ?? LANGUAGES[0];

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    // Focus the chosen language so arrow keys start from it.
    root.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      button.current?.focus();
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = Array.from(root.current?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? []);
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    const step = event.key === "ArrowDown" ? 1 : -1;
    items[(index + step + items.length) % items.length]?.focus();
    event.preventDefault();
  };

  return (
    <div ref={root} className={cn("relative", className)} onKeyDown={onKeyDown}>
      <button
        ref={button}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`${t("language.choose")}: ${current.name}`}
        onClick={() => setOpen((value) => !value)}
        className="text-muted-foreground hover:text-foreground hover:bg-muted/60 focus-visible:ring-ring/50 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm transition-colors outline-none focus-visible:ring-2 motion-reduce:transition-none"
      >
        <GlobeIcon aria-hidden className="size-4" />
        {current.name}
      </button>
      {open && (
        <div
          id={listId}
          role="menu"
          aria-label={t("language.choose")}
          className="bg-popover text-popover-foreground absolute top-full right-0 z-20 mt-1 flex min-w-36 flex-col rounded-lg border p-1 shadow-md"
        >
          {LANGUAGES.map((entry) => (
            <button
              key={entry.code}
              type="button"
              role="menuitemradio"
              aria-checked={entry.code === language}
              lang={entry.code}
              onClick={() => {
                setLanguage(entry.code);
                setOpen(false);
                button.current?.focus();
              }}
              className="hover:bg-muted focus-visible:bg-muted flex items-center justify-between gap-3 rounded-md px-2.5 py-1.5 text-start text-sm outline-none"
            >
              {entry.name}
              {entry.code === language && <CheckIcon aria-hidden className="size-4" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

/**
 * Restores the saved language, keeps <html lang> in step, and puts the language on every
 * chat message (the composer's runConfig becomes the agent's `configurable.language`).
 * The composer clears its runConfig after each send, so it is put back each time.
 * Must sit inside AssistantRuntimeProvider.
 */
export const LanguageSync: FC = () => {
  const aui = useAui();
  const language = useLanguage((s) => s.language);
  const restore = useLanguage((s) => s.restore);
  const sent = useAuiState((s) => s.composer.runConfig?.custom?.language);

  useEffect(() => restore(), [restore]);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  useEffect(() => {
    if (sent !== language) aui.composer().setRunConfig({ custom: { language } });
  }, [aui, sent, language]);

  return null;
};
