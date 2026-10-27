export const config = {
  llmMode: process.env.NEXT_PUBLIC_MARKETMESH_LLM_MODE ?? "scripted",
  threadsEnabled: process.env.NEXT_PUBLIC_COPILOTKIT_THREADS_ENABLED === "true",
  modelLabel:
    process.env.NEXT_PUBLIC_MARKETMESH_LLM_MODE === "live" ? "DeepSeek V4.1 Flash" : "Scripted demo",
  buyerApiUrl: process.env.BUYER_API_URL ?? "http://127.0.0.1:9100",
  registryUrl: process.env.REGISTRY_URL ?? "http://127.0.0.1:9105",
};
