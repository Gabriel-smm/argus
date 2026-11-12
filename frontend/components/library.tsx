"use client";

import { Button } from "@/components/ui/button";
import { useAnalysis, type AnalysisSummary } from "@/hooks/use-analysis";
import { inspectFile, MAX_FILE_BYTES, type FileCheck, type LayaRole } from "@/lib/laya-files";
import { cn } from "@/lib/utils";
import {
  CheckIcon,
  FileJsonIcon,
  FileSpreadsheetIcon,
  FileTextIcon,
  LoaderIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";

type LibraryFile = {
  id: string;
  name: string;
  size: number;
  type: string;
  addedAt: number;
  file: File;
  /** What the file turned out to hold; null while it is being read. */
  check: FileCheck | null;
};

type LibraryId = LayaRole;
type Kind = "pdf" | "json" | "docs" | "data" | "other";

const LIBRARIES: { id: LibraryId; label: string }[] = [
  { id: "knowledge", label: "Knowledge" },
  { id: "data", label: "Data" },
];

const LABELS: Record<LibraryId, string> = {
  knowledge: "Knowledge",
  data: "Data",
};

const NO_SELECTION: Record<LibraryId, string[]> = {
  knowledge: [],
  data: [],
};

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatAdded(timestamp: number) {
  const date = new Date(timestamp);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const days = Math.round((startOfToday.getTime() - startOfDate.getTime()) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function kindOf(file: Pick<LibraryFile, "name" | "type">): Kind {
  const name = file.name.toLowerCase();
  const type = file.type.toLowerCase();
  if (type === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (type.includes("json") || /\.jsonl?$/.test(name)) return "json";
  if (
    /\.(csv|tsv|xls|xlsx|xml)$/.test(name) ||
    type.includes("csv") ||
    type.includes("spreadsheet") ||
    type.includes("excel")
  ) {
    return "data";
  }
  if (
    /\.(doc|docx|txt|md|rtf|pages)$/.test(name) ||
    type.includes("word") ||
    type.startsWith("text/")
  ) {
    return "docs";
  }
  return "other";
}

async function inspect(file: File): Promise<FileCheck> {
  if (file.size > MAX_FILE_BYTES) {
    return { ok: false, detail: `Larger than ${formatSize(MAX_FILE_BYTES)}` };
  }
  try {
    return inspectFile(await file.text());
  } catch {
    return { ok: false, detail: "Could not read the file" };
  }
}

/** Whether a file can be run from the library it sits in, and what to say about it. */
function statusOf(file: LibraryFile, library: LibraryId) {
  const { check } = file;
  if (!check) return { usable: false, problem: null, text: "Checking…" };
  if (!check.ok) return { usable: false, problem: check.detail, text: null };
  if (check.role !== library) {
    return {
      usable: false,
      problem: `Looks like a ${check.role} file. Add it under ${LABELS[check.role]}.`,
      text: null,
    };
  }
  return { usable: true, problem: null, text: check.detail };
}

function describeSummary(summary: AnalysisSummary) {
  const rows = `${summary.observations} ${summary.observations === 1 ? "row" : "rows"}`;
  if (summary.questions.length !== 1) {
    return `${rows} · ${summary.questions.length} questions`;
  }
  return `${rows} · ${Object.keys(summary.questions[0].counts).length} types`;
}

function FileMark({ kind }: { kind: Kind }) {
  const tone = {
    pdf: "bg-red-500 text-white",
    json: "bg-amber-500 text-white",
    docs: "bg-blue-500 text-white",
    data: "bg-emerald-500 text-white",
    other: "bg-muted text-muted-foreground",
  }[kind];
  const Icon =
    kind === "json" ? FileJsonIcon : kind === "data" ? FileSpreadsheetIcon : FileTextIcon;
  return (
    <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-md", tone)}>
      <Icon className="size-3.5" />
    </span>
  );
}

export function Library() {
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [library, setLibrary] = useState<LibraryId>("knowledge");
  const [filesByLibrary, setFilesByLibrary] = useState<Record<LibraryId, LibraryFile[]>>({
    knowledge: [],
    data: [],
  });
  // Every selected file in a library takes part in a run, in this order.
  const [selected, setSelected] = useState(NO_SELECTION);
  // The files the active classification came from, while they are still listed.
  const [source, setSource] = useState(NO_SELECTION);
  const [query, setQuery] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const files = filesByLibrary[library];
  const { running, summary, error, run, clear, refresh } = useAnalysis();

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const chosen = (id: LibraryId) => {
    const byId = new Map(filesByLibrary[id].map((item) => [item.id, item]));
    return selected[id].flatMap((fileId) => {
      const file = byId.get(fileId);
      return file && statusOf(file, id).usable ? [file] : [];
    });
  };
  const knowledgeFiles = chosen("knowledge");
  const dataFiles = chosen("data");
  const missing = LIBRARIES.filter((item) => chosen(item.id).length === 0).map((item) =>
    item.label.toLowerCase(),
  );

  const addFiles = (list: FileList | File[]) => {
    const target = library;
    const next: LibraryFile[] = Array.from(list).map((file) => ({
      id: crypto.randomUUID(),
      name: file.name,
      size: file.size,
      type: file.type,
      addedAt: Date.now(),
      file,
      check: null,
    }));
    if (next.length === 0) return;
    setFilesByLibrary((current) => ({
      ...current,
      [target]: [...next, ...current[target]],
    }));
    const added = next.map((item) => item.id);
    for (const item of next) {
      void inspect(item.file).then((check) => {
        setFilesByLibrary((current) => ({
          ...current,
          [target]: current[target].map((file) =>
            file.id === item.id ? { ...file, check } : file,
          ),
        }));
        // Each usable file is selected, in the order it was added.
        if (check.ok && check.role === target) {
          setSelected((current) => {
            const ids = current[target].includes(item.id)
              ? current[target]
              : [...current[target], item.id];
            const batch = new Set(added);
            const previous = ids.filter((id) => !batch.has(id));
            const incoming = added.filter((id) => ids.includes(id));
            return { ...current, [target]: [...previous, ...incoming] };
          });
        }
      });
    }
  };

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return files.filter((file) => {
      if (needle && !file.name.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [files, query]);

  const toggle = (id: string) => {
    setSelected((current) => {
      const ids = current[library];
      const next = ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id];
      return { ...current, [library]: next };
    });
  };

  const remove = (id: string) => {
    setFilesByLibrary((current) => ({
      ...current,
      [library]: current[library].filter((file) => file.id !== id),
    }));
    setSelected((current) => ({
      ...current,
      [library]: current[library].filter((item) => item !== id),
    }));
    // The chat should not keep answering from a file the operator took away.
    if (source[library].includes(id)) {
      setSource(NO_SELECTION);
      void clear();
    }
  };

  const onRun = async () => {
    if (knowledgeFiles.length === 0 || dataFiles.length === 0) return;
    const next = {
      knowledge: knowledgeFiles.map((file) => file.id),
      data: dataFiles.map((file) => file.id),
    };
    const started = await run(
      knowledgeFiles.map((file) => file.file),
      dataFiles.map((file) => file.file),
    );
    if (started) setSource(next);
  };

  const onClear = () => {
    setSource(NO_SELECTION);
    void clear();
  };

  const onDragEnter = (event: DragEvent<HTMLElement>) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    dragDepth.current += 1;
    setDragOver(true);
  };

  const onDragOver = (event: DragEvent<HTMLElement>) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  };

  const onDragLeave = (event: DragEvent<HTMLElement>) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) setDragOver(false);
  };

  const openPicker = () => inputRef.current?.click();

  const onDrop = (event: DragEvent<HTMLElement>) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    dragDepth.current = 0;
    setDragOver(false);
    addFiles(event.dataTransfer.files);
  };

  return (
    <aside
      className="bg-sidebar flex h-[22rem] shrink-0 flex-col gap-3 border-b px-3 py-4 md:h-full md:w-[21.6rem] md:border-r md:border-b-0 md:px-3.5"
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <h2 className="shrink-0 px-1 text-base font-semibold tracking-tight">Library</h2>

      <label className="relative block shrink-0">
        <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search files"
          aria-label="Search files"
          className="placeholder:text-muted-foreground focus-visible:ring-ring/50 h-10 w-full rounded-lg border bg-transparent pr-3 pl-8 text-sm outline-none transition-colors focus-visible:ring-1"
        />
      </label>

      <div role="tablist" aria-label="Libraries" className="flex shrink-0 gap-1.5">
        {LIBRARIES.map((item) => {
          const active = library === item.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setLibrary(item.id)}
              className={cn(
                "h-8 flex-1 rounded-lg text-sm transition-colors",
                active
                  ? "bg-secondary text-foreground"
                  : "bg-muted/60 text-muted-foreground hover:text-foreground",
              )}
            >
              {item.label}
              {chosen(item.id).length > 0 && (
                <span className="ms-1.5 text-xs tabular-nums text-emerald-500">
                  {chosen(item.id).length}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div
        className={cn(
          "flex min-h-0 flex-1 flex-col gap-3",
          files.length === 0 && "group/empty cursor-pointer",
        )}
        onClick={files.length === 0 ? openPicker : undefined}
      >
        <ul
          role="listbox"
          aria-multiselectable="true"
          aria-label={`${LIBRARIES.find((item) => item.id === library)?.label} files`}
          className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto px-0.5 py-0.5"
        >
          {visible.length === 0 ? (
            <li className="flex flex-1 items-center justify-center px-2">
              <span
                className={cn(
                  "text-muted-foreground text-sm transition-all duration-300",
                  files.length === 0 &&
                    "group-hover/empty:text-foreground/80 group-hover/empty:-translate-y-1",
                )}
              >
                {files.length === 0 ? "No files yet" : "No matching files"}
              </span>
            </li>
          ) : (
            visible.map((item) => {
              const status = statusOf(item, library);
              const isSelected = status.usable && selected[library].includes(item.id);
              return (
                <li key={item.id} className="group relative">
                  <button
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    aria-disabled={!status.usable}
                    title={status.problem ? `${item.name}: ${status.problem}` : item.name}
                    onClick={status.usable ? () => toggle(item.id) : undefined}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-lg border px-2 py-2 text-left",
                      isSelected
                        ? "border-blue-500/70 bg-blue-500/15"
                        : "border-transparent hover:bg-muted/50",
                      !status.usable && "cursor-default",
                    )}
                  >
                    <FileMark kind={kindOf(item)} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm">{item.name}</span>
                      {status.problem ? (
                        <span className="text-destructive block truncate text-xs dark:text-red-200">
                          {status.problem}
                        </span>
                      ) : (
                        <span className="text-muted-foreground block truncate text-xs">
                          {status.text} · {formatSize(item.size)} · {formatAdded(item.addedAt)}
                        </span>
                      )}
                    </span>
                    <span
                      aria-hidden
                      className={cn(
                        "flex size-4 shrink-0 items-center justify-center rounded-[4px] border",
                        isSelected
                          ? "border-blue-500 bg-blue-500 text-white"
                          : "border-muted-foreground/40",
                        !status.usable && "invisible",
                      )}
                    >
                      {isSelected && <CheckIcon className="size-3" />}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Remove ${item.name}`}
                    onClick={() => remove(item.id)}
                    className="text-muted-foreground hover:text-foreground absolute top-1/2 right-8 flex size-5 -translate-y-1/2 items-center justify-center rounded opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                  >
                    <XIcon className="size-3.5" />
                  </button>
                </li>
              );
            })
          )}
        </ul>

        <div
          className={cn(
            "text-muted-foreground flex shrink-0 items-center gap-2 rounded-lg border border-dashed px-3 py-2.5 text-sm transition-colors duration-300",
            dragOver ? "border-foreground/50 bg-muted/30" : "border-foreground/25",
            files.length === 0 &&
              "group-hover/empty:border-foreground/45 group-hover/empty:bg-muted/20",
          )}
        >
          <FileTextIcon
            className={cn(
              "size-3.5 shrink-0 transition-transform duration-300",
              files.length === 0 && "group-hover/empty:-translate-y-0.5",
            )}
          />
          <p>
            Drop files anywhere, or{" "}
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                openPicker();
              }}
              className="text-blue-400 underline-offset-2 hover:underline"
            >
              browse
            </button>
          </p>
        </div>
      </div>

      <div className="flex shrink-0 flex-col gap-2">
        {error && (
          <p
            role="alert"
            className="border-destructive bg-destructive/10 text-destructive dark:bg-destructive/5 rounded-md border p-3 text-sm dark:text-red-200"
          >
            {error.field && <span className="font-medium">{LABELS[error.field]} file: </span>}
            {error.message}
          </p>
        )}
        {running ? (
          <p role="status" className="text-muted-foreground px-1 text-xs">
            Laya has the GPU, so chat is paused. This can take a minute.
          </p>
        ) : (
          summary && (
            <div className="flex items-start gap-2 px-1 text-xs">
              <span aria-hidden className="mt-1 size-1.5 shrink-0 rounded-full bg-emerald-500" />
              <p className="text-muted-foreground min-w-0 flex-1">
                <span className="text-foreground block">Active · {describeSummary(summary)}</span>
                <span
                  className="block truncate"
                  title={`${summary.knowledge_name} + ${summary.data_name}`}
                >
                  {summary.knowledge_name} + {summary.data_name}
                </span>
                {summary.row_offset > 0 ? (
                  <span className="block">
                    {`Rows ${summary.row_offset + 1}–${summary.row_offset + summary.observations} of ${summary.total_rows}`}
                  </span>
                ) : (
                  summary.total_rows > summary.observations && (
                    <span className="block">
                      First {summary.observations} of {summary.total_rows} rows
                    </span>
                  )
                )}
                {summary.low_confidence > 0 && (
                  <span className="block">{summary.low_confidence} low confidence</span>
                )}
                {summary.site_report && (
                  <span className="block">Site check: {summary.site_report.headline.toLowerCase()}</span>
                )}
              </p>
              <button
                type="button"
                onClick={onClear}
                className="text-blue-400 underline-offset-2 hover:underline"
              >
                Clear
              </button>
            </div>
          )
        )}
        <Button
          type="button"
          size="lg"
          className="w-full"
          disabled={running || missing.length > 0}
          aria-busy={running}
          onClick={onRun}
        >
          {running ? (
            <>
              <LoaderIcon className="animate-spin" />
              Classifying…
            </>
          ) : (
            "Run Laya"
          )}
        </Button>
        {!running && missing.length > 0 && (
          <p className="text-muted-foreground px-1 text-xs">
            Select a {missing.join(" file and a ")} file
          </p>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".json,.jsonl,application/json"
        className="sr-only"
        onChange={(event) => {
          if (event.target.files) addFiles(event.target.files);
          event.target.value = "";
        }}
      />
    </aside>
  );
}
