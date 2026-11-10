#pragma once

#include <cstdint>

namespace strata::core {
enum class ExpertEviction { lfu, lru, lfru };

// Only ranks victims. The caller must retain the victim's real count for tier admission.
inline bool colder_expert(ExpertEviction policy, uint32_t count, uint64_t tick,
                          uint32_t best_count, uint64_t best_tick, uint64_t clock) {
    if (policy == ExpertEviction::lru) return tick < best_tick;
    if (policy == ExpertEviction::lfru) {
        const double score = double(count) / (double(clock - tick) + 1.0);
        const double best = double(best_count) / (double(clock - best_tick) + 1.0);
        if (score != best) return score < best;
    } else if (count != best_count) {
        return count < best_count;
    }
    return tick < best_tick;
}
} // namespace strata::core
