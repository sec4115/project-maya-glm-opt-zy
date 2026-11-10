# Local API compatibility

The server exposes Anthropic Messages, OpenAI Chat Completions and the v1.1.21
Responses HTTP API. All three use the same model, FIFO, sampling and tool parser.

## Tool history

Anthropic `tool_use.id` and `tool_result.tool_use_id`, Chat Completions call `id`
and `tool_call_id`, and Responses `call_id` are retained. Contiguous result groups
are ordered to match their calls before rendering, including on templates without
IDs in their text. Unknown or duplicate result IDs are rejected when the preceding
calls provide IDs. Legacy histories without IDs still work. Anthropic `is_error`
results include a visible `[Tool execution failed]` marker without discarding images.

## Thinking budget and latency

`thinking.budget_tokens` controls the per-request engine budget, not just the
template effort. OpenAI clients can use the local `thinking_budget` extension.
Values must be positive integers. `thinking: {"type": "disabled"}` on Messages,
or `reasoning_effort: "none"` / `reasoning: {"effort": "none"}` on OpenAI requests,
disables thinking. Requests without a numeric budget retain the configured default.
The budget is clamped to the output allowance while reserving space for the answer.

`/metrics` request records include `queue_ms`, `first_token_ms` (after initial queue
admission), and the effective `thinking_budget`; the console reports these too.
These distinguish initial queue delay from time spent processing the prompt and
generating. Fair-slice waits after admission are included in the request duration,
not initial `queue_ms`.

The local M, L and XL configs set `STRATA_FAIR_SLICE_S=2` (also accepted as
`MAYA_FAIR_SLICE_S`). When another request waits,
an ongoing decode yields after its time slice and resumes from its accumulated
tokens later. This improves short-request latency under contention. It can add
context-switch/prompt-processing overhead; it does not preempt an ongoing prefill,
guarantee a two-second response, or create another GPU execution slot. Set it to
`0` to restore uninterrupted FIFO decoding. No Claude Code permission rules are
changed by these server fixes.

## Token counting

`POST /v1/messages/count_tokens` returns `{"input_tokens": N}` using the Messages
conversion, system prompt, tools, thinking defaults and model tokenizer. It does
not enter the inference queue. Image counting returns an explicit 400 rather than
reporting a misleading exact count. The dashboard's `/api/tokens` remains available
and labels its image-marker-only count as approximate.

## Responses for Codex and other clients

Use base URL `http://127.0.0.1:8080/v1` and HTTP `wire_api="responses"`.
Full input history with `store=false` remains supported. Supported:

- String or message input, developer/system instructions, reasoning effort and
  `max_output_tokens`.
- Function call/output history, tool choice and function argument deltas.
- Namespace groups of function/custom tools. Names are qualified internally, then
  restored to separate `namespace` and `name` fields in output and replayed history.
- `/v1/models` keeps the OpenAI `data` list and adds Codex's `models` capability
  catalog, so Codex can use the local context window and supported reasoning levels.
- Client custom tools, including raw string input/output history. Grammar definitions
  are supplied to the model as instructions; grammar-constrained decoding is not
  implemented. Custom input is delivered once its JSON wrapper is complete.
- Non-stream responses and ordered SSE events for visible reasoning, text, tool
  items and completion/incomplete status. SDK stream aggregators can reconstruct
  the final response. Reasoning is returned as `reasoning_text`; Codex's summary
  preference is accepted without a separate summarization call. No encrypted
  provider state is produced.
- Upstream response storage/retrieval/deletion, `previous_response_id`, input-item
  pagination, background jobs and cancellation. Namespace and custom-tool records
  also survive stored continuation. Records are bounded, expire, are scoped to
  the API key and are lost when the service restarts. See [RESPONSES.md](RESPONSES.md)
  for limits and endpoints. Background jobs share the same inference queue.
- JSON object / supported JSON Schema output and strict function parameters are
  validated before publication, using the project's `jsonschema` dependency.
  Validation is bounded; it is not constrained decoding and a model can fail it.
- Input images use the existing vision path, when a vision encoder is configured.
  This path has not been included in the new Responses smoke tests.

Explicitly unsupported: conversation objects, encrypted reasoning replay, remote
built-in tools, WebSocket transport and server-side compaction. Unsupported
input/tool types return 400. Use client tools for local execution; the adapter
never executes a returned tool call.

Protocol references:
[Responses streaming](https://developers.openai.com/api/reference/resources/responses/streaming-events),
[function calling](https://developers.openai.com/api/docs/guides/function-calling),
[Anthropic tool results](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls).
