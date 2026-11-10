# Prefix reuse and KV cache tuning

There are separate caches: reused prompt state avoids prefill, while streamed KV
blocks avoid PCIe reads during attention. A high rate in one does not imply a high
rate in the other. Expert weight residency is another independent cache.

## Prefix stability

Tool schema objects are rendered in canonical key order. Tool list order remains
the first-seen order of that name set; arrays such as enum, required and examples
retain their order and values. Normalization does not rewrite instructions,
messages or replayed function arguments. Set `STRATA_PREFIX_CANONICAL_TOOLS=0` in
the config's env to restore the old mapping-order behavior (server restart needed).

This handles equivalent JSON objects arriving with different key insertion order.
It cannot reuse a prefix whose actual instructions, schemas or history changed.
Clients should keep stable instructions and tool definitions ahead of changing
content, without moving instructions to a different priority or dropping history.

GLM's RAM checkpoints protect the shortest valid shared prefix while later states
rotate by least use. Long prompts retain their system/user boundary alongside
recent periodic checkpoints rather than dropping it solely because the mark count
exceeded the cap. `STRATA_GLM_CKPT_PIN_ROOT=0` restores the previous retention policy.
All existing validity checks and checkpoint invalidation on branch writes remain.

## Conversation switching

Streamed KV has an authoritative pinned RAM copy. Slots now write/read that copy
directly using its CPU address after stream synchronization. Device-only states
still use bounded staging buffers. The slot file format and validation are unchanged.
This removes an extra host buffer copy without adding a second full session cache
to RAM. `STRATA_GLM_SLOT_DIRECT_HOST=0` uses the legacy staging path for comparison.

These optimizations do not put multiple conversations in VRAM at once. Restoring a
slot still invalidates the old conversation's KV residency maps before attention
reads the new conversation. Never preserve a map across different histories merely
to increase the reported hit rate.

## Measurements

`tools/benchmark_kv_cache.py` runs a real HTTP service on port 18091 with isolated
conversation slots and expert usage/profile writes disabled. It records first-text
latency, engine prompt/decode clocks, prefix reuse, recall answers and output hashes.
The long fixture exceeds the 32K residency window. `--phase root` additionally grows
a conversation through several periodic checkpoints before returning to its root.

`tools/run_kv_plan.py` runs explicit cases sequentially. Compare FP16/INT8 and 32768/
65536 resident positions with the same production vision memory allowance. More KV
residency can displace experts; INT8 can alter numerical outputs. Choose on total
latency and decode throughput, with accuracy checks, rather than KV hit rate alone.
The timing lines are cumulative KV block counters; use deltas for comparisons when
the histories and restore counts differ.
