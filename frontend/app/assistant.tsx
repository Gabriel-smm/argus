"use client";

import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useStreamRuntime } from "@assistant-ui/react-langchain";

import { Thread } from "@/components/assistant-ui/elements/thread.aui";
import { DemoBadge, DemoControlsShortcut } from "@/components/demo-controls";
import { LanguageMenu, LanguageSync } from "@/components/language-menu";
import { Library } from "@/components/library";
import { useT } from "@/lib/i18n";

export function Assistant() {
  const { t } = useT();
  const apiUrl =
    process.env.NEXT_PUBLIC_LANGGRAPH_API_URL || "http://localhost:2024";

  const runtime = useStreamRuntime({
    assistantId: process.env.NEXT_PUBLIC_LANGGRAPH_ASSISTANT_ID || "agent",
    apiUrl,
    // Over SSE the SDK waits for a fetch that Firefox only settles once the
    // stream has data, and an idle subscription never sends any, so replies
    // never arrive there.
    transport: "websocket",
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="relative flex h-full min-h-0 flex-col md:flex-row">
        <Library />
        <div className="min-h-0 min-w-0 flex-1">
          <Thread />
        </div>
        <div className="absolute top-[13px] right-5 z-10 flex items-center gap-3">
          <LanguageMenu />
          <p className="text-muted-foreground pointer-events-none flex items-center gap-2 text-sm font-normal">
            {t("app.local")}
            <span
              aria-hidden
              className="size-1.5 shrink-0 rounded-full bg-emerald-500"
            />
          </p>
        </div>
      </div>
      <LanguageSync />
      <DemoControlsShortcut />
      {/* Fixed to the bottom-right corner, on every screen. */}
      <DemoBadge />
    </AssistantRuntimeProvider>
  );
}
