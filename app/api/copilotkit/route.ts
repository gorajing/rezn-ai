import {
  CopilotRuntime,
  OpenAIAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";

export const runtime = "nodejs";

const ENDPOINT = "/api/copilotkit";

const copilotRuntime = new CopilotRuntime();

export const POST = async (req: Request) => {
  // The copilot needs an LLM key to generate responses. Return a clear, handled
  // 503 when it is missing instead of letting the runtime throw an unhandled
  // rejection. The rest of the app (provider, hooks, UI) still runs without it.
  if (!process.env.OPENAI_API_KEY) {
    return Response.json(
      {
        error:
          "OPENAI_API_KEY is not set. Copy .env.local.example to .env.local and add your key to enable the copilot.",
      },
      { status: 503 },
    );
  }

  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime: copilotRuntime,
    serviceAdapter: new OpenAIAdapter({ model: "gpt-4o-mini" }),
    endpoint: ENDPOINT,
  });

  return handleRequest(req);
};
