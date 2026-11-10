// Bounded expert-local dependencies for CPU gate/up -> hidden quantization -> down.
// One worker loop per active pool thread, so waiting down jobs cannot starve unclaimed gate jobs.
#pragma once
#include <algorithm>
#include <array>
#include <atomic>
#include <thread>

namespace strata::core {
template<class Pool, class Gate, class Quant, class Down>
void expert_pipeline(Pool& pool, int experts, int parts, Gate gate, Quant quant, Down down) {
    if (experts <= 0) return;
    // The GLM route is bounded to 8 experts. Caller uses the original path for larger routes.
    std::array<std::atomic<int>, 8> gate_left{}, down_next{};
    std::array<std::atomic<bool>, 8> ready{};
    for (int e = 0; e < experts; ++e) gate_left[e].store(parts, std::memory_order_relaxed);
    std::atomic<int> next_gate{0}, down_done{0};
    const int total = experts * parts;
    pool.run(pool.active(), [&](int worker) {
        int spins = 0;
        while (down_done.load(std::memory_order_acquire) < total) {
            bool worked = false;
            for (int j = 0; j < experts; ++j) {
                const int e = (worker + j) % experts;
                if (!ready[e].load(std::memory_order_acquire)) continue;
                int p = down_next[e].load(std::memory_order_relaxed);
                while (p < parts && !down_next[e].compare_exchange_weak(p, p + 1, std::memory_order_relaxed)) {}
                if (p < parts) {
                    down(e, p, parts);
                    down_done.fetch_add(1, std::memory_order_release);
                    worked = true;
                    break;
                }
            }
            if (worked) continue;
            int job = next_gate.load(std::memory_order_relaxed);
            while (job < total && !next_gate.compare_exchange_weak(job, job + 1, std::memory_order_relaxed)) {}
            if (job < total) {
                const int e = job / parts;
                gate(e, job % parts, parts);
                // acq_rel collects every gate fragment before the last one quantizes the complete expert.
                if (gate_left[e].fetch_sub(1, std::memory_order_acq_rel) == 1) {
                    quant(e);
                    ready[e].store(true, std::memory_order_release);
                }
                continue;
            }
            if ((++spins & 255) == 0) std::this_thread::yield();
        }
    });
}
} // namespace strata::core
