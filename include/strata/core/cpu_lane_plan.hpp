#pragma once

#include <algorithm>
#include <array>
#include <cmath>

namespace strata::core {

using CpuLaneCosts = std::array<std::array<double, 9>, 9>;

inline bool valid_cpu_lane_plan(const char* text) {
    if (text == nullptr) return false;
    for (int f = 0; f <= 8; ++f)
        if (text[f] < '0' || text[f] > '0' + f) return false;
    return text[9] == '\0';
}

// Each row is an observed end-to-end cost for f RAM experts, of which k run
// on the CPU. Keep the startup estimate unless a measured alternative wins by
// both a relative and absolute margin; incomplete rows retain that estimate.
inline unsigned long long cpu_lane_joint_plan(const CpuLaneCosts& ms, int max_ram,
                                              unsigned long long fallback,
                                              double relative_margin = 0.03,
                                              double absolute_margin_ms = 0.005) {
    unsigned long long plan = fallback;
    for (int f = 1; f <= std::min(8, max_ram); ++f) {
        const int original = (int) ((fallback >> (4 * f)) & 15ull);
        if (original > f) continue;
        bool complete = true;
        for (int k = 0; k <= f; ++k) complete = complete && std::isfinite(ms[f][k]) && ms[f][k] > 0.0;
        if (!complete) continue;
        int best = original;
        for (int k = 0; k <= f; ++k)
            if (ms[f][k] < ms[f][best]) best = k;
        const double gain = ms[f][original] - ms[f][best];
        if (gain > std::max(absolute_margin_ms, ms[f][original] * relative_margin)) {
            plan &= ~(15ull << (4 * f));
            plan |= (unsigned long long) best << (4 * f);
        }
    }
    return plan;
}

// Total CPU batch times, not per-expert averages. A route contains at most eight
// RAM-tier experts. Invalid/incomplete measurements retain the linear estimate.
inline unsigned long long cpu_lane_plan(double cpu_ms, double pcie_ms,
                                        const std::array<double, 9>& batch_ms,
                                        double overhead_ms = 0.04) {
    bool measured = batch_ms[0] == 0.0;
    for (int k = 1; k <= 8; ++k)
        measured = measured && std::isfinite(batch_ms[k]) && batch_ms[k] > 0.0;
    unsigned long long plan = 0;
    for (int f = 1; f <= 8; ++f) {
        int chosen = 0;
        double best = pcie_ms * f;
        for (int k = 1; k <= f; ++k) {
            const double cost = std::max(pcie_ms * (f - k),
                                        overhead_ms + (measured ? batch_ms[k] : cpu_ms * k));
            if (cost < best - 1e-9) {
                best = cost;
                chosen = k;
            }
        }
        plan |= static_cast<unsigned long long>(chosen) << (4 * f);
    }
    return plan;
}

}  // namespace strata::core
