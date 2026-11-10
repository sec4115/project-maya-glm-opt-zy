#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>

namespace strata::spec {

// Recent wall time for each draft length, including length zero (plain decode).
// Nine samples per length bound both storage and work; a single scheduling stall
// cannot dominate a full window's median. No device synchronization is needed.
class WindowRuntime {
public:
    static constexpr int kLengths = 9;
    static constexpr int kSamples = 9;

    // True only when a mature median moved by more than 20% since its reference.
    // The caller can then remeasure other lengths instead of waiting for its
    // normal, progressively longer probe interval. Invalid timings are ignored.
    bool observe(int drafts, double ms) {
        if (drafts < 0 || drafts >= kLengths || !std::isfinite(ms) || ms <= 0.0) return false;
        auto& w = windows_[static_cast<std::size_t>(drafts)];
        w.samples[static_cast<std::size_t>(w.next)] = ms;
        w.next = (w.next + 1) % kSamples;
        w.size = std::min(w.size + 1, kSamples);
        auto sorted = w.samples;
        std::sort(sorted.begin(), sorted.begin() + w.size);
        const int middle = w.size / 2;
        w.median = w.size % 2 ? sorted[static_cast<std::size_t>(middle)]
                             : sorted[static_cast<std::size_t>(middle - 1)] * 0.5 +
                                   sorted[static_cast<std::size_t>(middle)] * 0.5;
        if (w.size < 5) return false;
        if (w.reference == 0.0) {
            w.reference = w.median;
            return false;
        }
        if (std::abs(w.median - w.reference) > w.reference * 0.2) {
            w.reference = w.median;
            return true;
        }
        return false;
    }

    double cost_ms(int drafts) const {
        return drafts >= 0 && drafts < kLengths ? windows_[static_cast<std::size_t>(drafts)].median : 0.0;
    }

private:
    struct Window {
        std::array<double, kSamples> samples{};
        int next = 0, size = 0;
        double median = 0.0, reference = 0.0;
    };
    std::array<Window, kLengths> windows_{};
};

}  // namespace strata::spec
