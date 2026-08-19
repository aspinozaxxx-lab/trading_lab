# Isolated document LLM runner

Local-only extraction tool for financial reports. It does not expose a network service and its CLI
has no inputs for market prices, future returns, or target labels.

Pinned model: `Qwen/Qwen3-VL-8B-Instruct` at revision
`0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` (Apache-2.0).

Run:

```bash
/opt/Tester/market-lab-doc-llm/run_local.sh --input report.pdf
```

Each invocation creates an immutable run folder under `runs/` with strict evidence JSON, generated
JSON Schema, raw model output, dependency freeze, hashes, runtime, and peak allocated VRAM.
