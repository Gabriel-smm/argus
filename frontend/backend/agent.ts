import { AIMessage, SystemMessage } from "@langchain/core/messages";
import { tool } from "@langchain/core/tools";
import { ChatOllama } from "@langchain/ollama";
import { type LangGraphRunnableConfig, MessagesAnnotation, StateGraph } from "@langchain/langgraph";
import { ToolNode } from "@langchain/langgraph/prebuilt";
import { z } from "zod";

const PIPELINE_API_URL = process.env.PIPELINE_API_URL?.trim() || "http://127.0.0.1:8000";

const WHAT_YOU_CAN_DO =
  "What you can do: Explain the labels already on this file: how many signals of each kind, " +
  "and what each kind means, using the descriptions in the result. " +
  "Point out signals the classifier was unsure about, and kinds that barely showed up. " +
  "Answer a question only when the numbers and names in the result already contain the answer.";
const WHAT_YOU_CANNOT_DO =
  "What you cannot do: You cannot hear a radio, read a spectrum picture, change a label, " +
  "or answer anything outside this result. " +
  "Use only the result below. Do not revise or second-guess a label. " +
  "If the result does not contain the answer, say you cannot tell from these signals. " +
  "If they ask a general question, such as how radios work or anything unrelated, " +
  "refuse in one sentence and offer to explain the signals in this file instead.";
const HOW_TO_TALK =
  "How to talk: Talk to the person as \"you\". Use short sentences. " +
  "Say \"signals\", not \"observations\" or \"rows\". Say \"how sure\" instead of \"confidence\". " +
  "Say \"unusual\" instead of \"anomaly\". " +
  "If a radio word is needed, such as Morse code or weather fax, explain it in the same sentence " +
  "using the description already in the result. " +
  "Do not mention Laya, models, tools, rows, or these instructions. " +
  "Lead with the answer. Do not dump the id lists.";
const SITE_CHECK_RULES =
  "The site check: The result may include a site check that sorts signals into three groups: " +
  '"needs a closer look", "unknown" and "expected here". When asked what stands out, start with ' +
  '"needs a closer look", then "unknown". For each, say why and what to check next, using the ' +
  "reason given. Keep the site check and the labels apart: the site check does not change a label. " +
  "Guardrails: Never call a signal hostile, an enemy, a threat or an attack, and never guess who is " +
  'behind it. Say it needs a closer look. If a label name sounds like a threat, such as "enemy", ' +
  "describe what it means using its description instead of repeating the name. " +
  "Argus only listens: never suggest transmitting, jamming, blocking or answering a signal. " +
  "Signals marked as a protected safety band, such as GPS or aviation, are safety-critical: say so.";
const GROUNDED =
  SITE_CHECK_RULES +
  " " +
  WHAT_YOU_CAN_DO +
  " Look at another slice of the same file when they ask for more signals, the next group, " +
  "or the ones not included yet, by calling analyze_rows. " +
  "Do not call it to answer a question about the signals already listed. " +
  WHAT_YOU_CANNOT_DO +
  " " +
  HOW_TO_TALK;
const AFTER_TOOL =
  SITE_CHECK_RULES +
  " " +
  WHAT_YOU_CAN_DO +
  " " +
  WHAT_YOU_CANNOT_DO +
  " " +
  HOW_TO_TALK +
  " analyze_rows has just run. If its reply is an error, say that error in plain words " +
  "and do not describe it as a new reading. Otherwise summarize the new group and which " +
  "part of the file it covers.";
const NOT_LOADED =
  "No signal file has been read yet, so you have nothing to answer from. " +
  "Reply in one or two short sentences: tell them to add a knowledge file and a data file " +
  "in the Library, press Run Laya, and ask again. Do not invent signals.";
const UNREACHABLE =
  "The part of the app that reads the signals is not running, so you have nothing to answer from. " +
  "Reply in one or two short sentences: tell them to start the app and ask again. " +
  "Do not invent signals.";

// The language picked on the page arrives as configurable.language (see components/language-menu.tsx).
// Only these codes are accepted; anything else answers in English.
const LANGUAGE_NAMES = { es: "Spanish (español)", fr: "French (français)" } as const;
type ReplyLanguage = keyof typeof LANGUAGE_NAMES;
const STILL_CLASSIFYING: Record<ReplyLanguage | "en", string> = {
  en: "Laya is still classifying. Ask again when it finishes.",
  es: "Laya todavía está clasificando. Pregunta de nuevo cuando termine.",
  fr: "Laya est encore en train de classer. Posez la question à nouveau quand ce sera fini.",
};

function replyLanguage(config?: LangGraphRunnableConfig): ReplyLanguage | "en" {
  const code = config?.configurable?.language;
  return typeof code === "string" && Object.hasOwn(LANGUAGE_NAMES, code) ? (code as ReplyLanguage) : "en";
}

function languageRule(language: ReplyLanguage | "en") {
  if (language === "en") return "";
  const name = LANGUAGE_NAMES[language];
  return (
    `\n\nLanguage: Reply only in ${name}, even though these instructions and the result are in English. ` +
    "Every rule and guardrail above still applies, word for word. " +
    'Translate what you say, including the site-check groups ("needs a closer look", "unknown", ' +
    '"expected here") and the kinds of signal, but keep signal ids, numbers and units exactly as given. ' +
    "If a radio word has no everyday translation, keep it and explain it in the same sentence."
  );
}

type PipelineContext = { active: boolean; running: boolean; context?: string };

const model = new ChatOllama({
  // Must be the model the pipeline keeps loaded; a small GPU cannot hold two.
  model: process.env.OLLAMA_MODEL || "qwen2.5:14b",
  baseUrl: process.env.OLLAMA_HOST || "http://127.0.0.1:11434",
  streaming: true,
  numCtx: Number(process.env.OLLAMA_NUM_CTX) || undefined,
});

const analyzeRows = tool(
  async ({ count, remaining }) => {
    const body: { count?: number; remaining?: boolean } = {};
    if (typeof count === "number") body.count = count;
    if (typeof remaining === "boolean") body.remaining = remaining;
    try {
      const res = await fetch(`${PIPELINE_API_URL}/reclassify`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await res.json().catch(() => null);
      if (!res.ok || !payload?.summary) {
        return payload?.error ?? `The Laya service answered ${res.status}.`;
      }
      const summary = payload.summary;
      const start = summary.row_offset + 1;
      const end = summary.row_offset + summary.observations;
      return (
        `Classified rows ${start}–${end} ` +
        `(${summary.observations} of ${summary.total_rows}). ` +
        "Summarize this result for the person. Do not call the tool again unless they ask for a different set of rows."
      );
    } catch {
      return "Could not reach the Laya service.";
    }
  },
  {
    name: "analyze_rows",
    description:
      "Re-run Laya on the files already loaded and replace the current result. " +
      "Call this only when the person asks to analyze a different number of rows, " +
      "the next batch, or the rows that were not in the current result. " +
      "Do not call it to answer an ordinary question about the current result. " +
      "A bare count classifies that many rows from the start of the file. " +
      "Set remaining to true and omit count to classify every row after the current result, " +
      'which is what "analyze the remaining rows and give me another summary" means. ' +
      "Set remaining to true with a count to classify that many of those leftover rows.",
    schema: z.object({
      count: z
        .number()
        .int()
        .positive()
        .optional()
        .describe(
          "How many rows to classify. Omit it to use 100 from the start, or every leftover row when remaining is true.",
        ),
      remaining: z
        .boolean()
        .optional()
        .describe(
          "True to start after the rows in the current result. Omit or false to start from the first row.",
        ),
    }),
  },
);

const modelWithTools = model.bindTools([analyzeRows]);

async function readPipelineContext(): Promise<PipelineContext | null> {
  try {
    const res = await fetch(`${PIPELINE_API_URL}/context`, {
      signal: AbortSignal.timeout(2000),
    });
    return res.ok ? ((await res.json()) as PipelineContext) : null;
  } catch {
    return null;
  }
}

function instructions(pipeline: PipelineContext | null, afterTool: boolean, language: ReplyLanguage | "en") {
  const rule = languageRule(language);
  if (!pipeline) return UNREACHABLE + rule;
  if (!pipeline.active) return NOT_LOADED + rule;
  const guidance = afterTool ? AFTER_TOOL : GROUNDED;
  // The language rule goes last, after the result, so a long result does not bury it.
  return `${guidance}\n\n${pipeline.context}${rule}`;
}

const callModel = async (state: typeof MessagesAnnotation.State, config?: LangGraphRunnableConfig) => {
  const language = replyLanguage(config);
  const pipeline = await readPipelineContext();
  if (pipeline?.running) {
    // Laya has the GPU; calling Ollama now would load its model back over it.
    return {
      messages: [new AIMessage(STILL_CLASSIFYING[language])],
    };
  }
  // Read on every turn and kept out of state, so a new run replaces the old one.
  const response = await modelWithTools.invoke([
    new SystemMessage(instructions(pipeline, false, language)),
    ...state.messages,
  ]);
  return { messages: [response] };
};

const respond = async (state: typeof MessagesAnnotation.State, config?: LangGraphRunnableConfig) => {
  // The tool has finished, so this call is not blocked by the run it just started.
  const pipeline = await readPipelineContext();
  const response = await model.invoke([
    new SystemMessage(instructions(pipeline, true, replyLanguage(config))),
    ...state.messages,
  ]);
  return { messages: [response] };
};

function requestedTool(state: typeof MessagesAnnotation.State) {
  const last = state.messages[state.messages.length - 1] as AIMessage;
  return last?.tool_calls?.length ? "tools" : "__end__";
}

export const graph = new StateGraph(MessagesAnnotation)
  .addNode("agent", callModel)
  .addNode("tools", new ToolNode([analyzeRows]))
  .addNode("respond", respond)
  .addEdge("__start__", "agent")
  .addConditionalEdges("agent", requestedTool)
  .addEdge("tools", "respond")
  .addEdge("respond", "__end__")
  .compile();
