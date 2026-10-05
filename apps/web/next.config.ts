import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the docker compose `web` service.
  output: "standalone",
  poweredByHeader: false,
  // Do not let `next dev` write AGENTS.md / CLAUDE.md here: the repo-root CLAUDE.md is the
  // single source of agent rules.
  agentRules: false,
};

export default nextConfig;
