import {
  CopilotRuntime,
  OpenAIAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import OpenAI from "openai";

export const runtime = "nodejs";

const ENDPOINT = "/api/copilotkit";
const WANDB_INFERENCE_BASE_URL = "https://api.inference.wandb.ai/v1";
const WANDB_INFERENCE_MODEL = "openai/gpt-oss-120b";
const OPENAI_FALLBACK_MODEL = "gpt-4o-mini";

const copilotRuntime = new CopilotRuntime();

function llmKey() {
  const wandbKey = process.env.WANDB_INFERENCE_API_KEY || process.env.WANDB_API_KEY;
  if (wandbKey) {
    return { provider: "wandb" as const, apiKey: wandbKey };
  }
  if (process.env.OPENAI_API_KEY) {
    return { provider: "openai" as const, apiKey: process.env.OPENAI_API_KEY };
  }
  return null;
}

function serviceAdapter() {
  const key = llmKey();
  if (!key) return null;

  if (key.provider === "wandb") {
    const openai = new OpenAI({
      baseURL: WANDB_INFERENCE_BASE_URL,
      apiKey: key.apiKey,
      project: process.env.WEAVE_PROJECT || process.env.WANDB_PROJECT,
    });
    return new OpenAIAdapter({ openai, model: WANDB_INFERENCE_MODEL });
  }

  return new OpenAIAdapter({ model: OPENAI_FALLBACK_MODEL });
}

export const POST = async (req: Request) => {
  // The copilot needs an LLM key to generate responses. Return a clear, handled
  // 503 when it is missing instead of letting the runtime throw an unhandled
  // rejection. The rest of the app (provider, hooks, UI) still runs without it.
  const adapter = serviceAdapter();
  if (!adapter) {
    return Response.json(
      {
        error:
          "No LLM key is set. Copy .env.local.example to .env.local and add WANDB_INFERENCE_API_KEY, WANDB_API_KEY, or OPENAI_API_KEY to enable the copilot.",
      },
      { status: 503 },
    );
  }

  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime: copilotRuntime,
    serviceAdapter: adapter,
    endpoint: ENDPOINT,
  });

  return handleRequest(req);
};
