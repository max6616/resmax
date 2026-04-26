# Resmax Multimodel MCP

This is a project-local Codex MCP server for calling official model APIs as
review tools. It currently exposes DeepSeek V4 Pro through the official
DeepSeek OpenAI-compatible Chat Completions endpoint.

## Secret Setup

Create `.secrets/deepseek.env` from the tracked example:

```bash
cp .secrets/deepseek.env.example .secrets/deepseek.env
```

Then fill in `DEEPSEEK_API_KEY`.

## Codex Configuration

The project-level `.codex/config.toml` registers this server as
`resmax_multimodel`. Codex may need a restart before a newly added project MCP
server appears in the active tool list.

## Tool

- `deepseek_review`: Sends a review prompt to `deepseek-v4-pro` with thinking
  mode enabled. The tool returns the final answer, metadata, usage, and whether
  reasoning content was present. Raw reasoning content is omitted by default.
