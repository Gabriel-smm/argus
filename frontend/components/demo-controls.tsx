"use client";

import { useEffect, useId, useRef, useState, type FC } from "react";
import { ChevronDownIcon, FlaskConicalIcon, XIcon } from "lucide-react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { SCENES, useAnalysis, type SceneName } from "@/hooks/use-analysis";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/**
 * Which demo scene Start scan plays. Kept off the main screen, so it looks like the real
 * product: in the Library's Demo controls, and in a popover on Shift+D for recordings
 * with the Library hidden.
 */
const SceneChoices: FC<{ name: string; autoFocus?: boolean }> = ({ name, autoFocus }) => {
  const { t } = useT();
  const scene = useAnalysis((s) => s.scene);
  const setScene = useAnalysis((s) => s.setScene);

  return (
    <fieldset className="flex flex-col gap-0.5">
      <legend className="sr-only">{t("scene.choose")}</legend>
      {SCENES.map((option) => (
        <label
          key={option}
          className="hover:bg-muted/60 has-[:focus-visible]:ring-ring/50 flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm has-[:focus-visible]:ring-2"
        >
          <input
            type="radio"
            name={name}
            value={option}
            checked={scene === option}
            onChange={() => setScene(option)}
            autoFocus={autoFocus && scene === option}
            className="accent-foreground"
          />
          {t(`scene.${option}`)}
        </label>
      ))}
    </fieldset>
  );
};

/** Collapsible "Demo controls" at the bottom of the Library. */
export const DemoControlsSection: FC = () => {
  const { t } = useT();
  return (
    <Collapsible className="border-t pt-2">
      <CollapsibleTrigger className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 group flex w-full items-center gap-2 rounded-md px-1 py-1 text-xs font-medium outline-none focus-visible:ring-2">
        <FlaskConicalIcon aria-hidden className="size-3.5" />
        <span className="flex-1 text-start">{t("demo.controls")}</span>
        <ChevronDownIcon
          aria-hidden
          className="size-3.5 transition-transform group-data-[panel-open]:rotate-180 motion-reduce:transition-none"
        />
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-1">
        <SceneChoices name="demo-scene-library" />
        <p className="text-muted-foreground px-2 pt-1 text-xs">{t("demo.shortcut")}</p>
      </CollapsibleContent>
    </Collapsible>
  );
};

function isTyping(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/**
 * Restores the remembered scene, and opens the same choices on Shift+D in a small popover.
 * Shift+D is ignored while typing, so a capital D in the chat still works.
 */
export const DemoControlsShortcut: FC = () => {
  const { t } = useT();
  const restoreScene = useAnalysis((s) => s.restoreScene);
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const titleId = useId();

  useEffect(() => restoreScene(), [restoreScene]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && open) {
        setOpen(false);
        return;
      }
      const shiftD = event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey && event.code === "KeyD";
      if (!shiftD || isTyping(event.target)) return;
      event.preventDefault();
      if (!open) returnFocus.current = document.activeElement as HTMLElement | null;
      setOpen((value) => !value);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) return;
    returnFocus.current?.focus?.();
    returnFocus.current = null;
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!panel.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  if (!open) return null;
  return (
    <div
      ref={panel}
      role="dialog"
      aria-labelledby={titleId}
      className="bg-popover text-popover-foreground fade-in zoom-in-95 animate-in fixed right-5 bottom-5 z-50 w-56 rounded-xl border p-2 shadow-lg duration-150 motion-reduce:animate-none"
    >
      <div className="flex items-center gap-2 px-2 pb-1">
        <FlaskConicalIcon aria-hidden className="text-muted-foreground size-3.5" />
        <p id={titleId} className="flex-1 text-xs font-medium">
          {t("demo.controls")}
        </p>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label={t("demo.close")}
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 rounded p-0.5 outline-none focus-visible:ring-2"
        >
          <XIcon aria-hidden className="size-3.5" />
        </button>
      </div>
      <SceneChoices name="demo-scene-popover" autoFocus />
    </div>
  );
};

/**
 * A small badge on the main screen that always says "Demo data". Its tooltip names the
 * scenario: the one on screen when a result is shown, otherwise the one Start scan plays.
 */
export const DemoBadge: FC = () => {
  const { t } = useT();
  const picked = useAnalysis((s) => s.scene);
  const shown = useAnalysis((s) => (s.showResult && !s.scanning ? s.summary?.scene?.name : undefined));
  const scene = (SCENES.includes(shown as SceneName) ? shown : picked) as SceneName;
  const tip = t(scene === "campus" ? "demo.tipCampus" : "demo.tipAndrew", { scene: t(`scene.${scene}`) });

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          className={cn(
            "text-muted-foreground/80 hover:text-muted-foreground focus-visible:ring-ring/50 rounded-full border border-dashed px-2 py-0.5 text-[11px] outline-none focus-visible:ring-2",
          )}
        >
          {t("demo.badge")}
          <span className="sr-only">: {tip}</span>
        </TooltipTrigger>
        <TooltipContent side="bottom">{tip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};
