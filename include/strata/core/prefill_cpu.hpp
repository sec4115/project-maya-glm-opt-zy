#pragma once
#include <cstdint>

namespace strata::core {
// Keep the established threshold by default. An explicit small-batch limit may
// admit the CPU as an additional parallel lane even when DMA alone is faster;
// the existing row-cost planner still limits how much work it can take.
inline bool prefill_cpu_eligible(bool enabled, bool pool, double cpu_ms, double pcie_ms,
                                 int64_t rows, int64_t small_limit, double cost_gate = 2.0) {
    return enabled && pool && cpu_ms > 0.0 && pcie_ms > 0.0 &&
           (pcie_ms > cost_gate * cpu_ms || (rows > 0 && rows <= small_limit));
}
}
