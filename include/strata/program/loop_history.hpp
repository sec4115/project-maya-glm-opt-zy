#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace strata::program {

// Exact periodicity of a suffix, without keeping or rescanning the generated text.
// For each period p, equal_[p-1] counts consecutive matches token[i] == token[i-p].
// A window of w tokens repeats with period p iff its last w-p comparisons match.
// Work and storage are bounded by the guard's maximum period, not output length.
class LoopHistory {
public:
    static constexpr std::size_t kMaxPeriod = 32;

    void push_back(int token) {
        for (std::size_t p = 1; p <= kMaxPeriod; ++p) {
            auto& run = equal_[p - 1];
            run = count_ >= p && tail_[(count_ - p) % kMaxPeriod] == token ? run + 1 : 0;
        }
        tail_[count_ % kMaxPeriod] = token;
        ++count_;
    }

    int looping(int window) const {
        if (window <= 0 || count_ < static_cast<std::uint64_t>(window)) return 0;
        for (int p = 1; p <= static_cast<int>(kMaxPeriod) && p < window / 4; ++p)
            if (equal_[static_cast<std::size_t>(p - 1)] >= static_cast<std::uint64_t>(window - p)) return p;
        return 0;
    }

    void clear() {
        count_ = 0;
        equal_.fill(0);
    }

private:
    std::array<int, kMaxPeriod> tail_{};
    std::array<std::uint64_t, kMaxPeriod> equal_{};
    std::uint64_t count_ = 0;
};

}  // namespace strata::program
