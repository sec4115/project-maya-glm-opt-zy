#include "strata/program/loop_history.hpp"
#include "strata/core/split_groups.hpp"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <vector>

using strata::program::LoopHistory;

// Reference: the previous production guard. Keep its integer division and
// first-matching-period rule, including windows too small to admit any period.
static int reference(const std::vector<int>& history, int window) {
    const int n = (int) history.size();
    if (window <= 0 || n < window) return 0;
    for (int p = 1; p <= 32 && p < window / 4; ++p) {
        bool repeated = true;
        for (int i = n - window + p; i < n && repeated; ++i)
            repeated = history[(size_t) i] == history[(size_t) (i - p)];
        if (repeated) return p;
    }
    return 0;
}

static void check(bool ok, const char* message) {
    if (!ok) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

static void differential(const std::vector<int>& tokens, int reset_every = 0) {
    LoopHistory history;
    std::vector<int> old;
    const int windows[] = {-10, 0, 1, 4, 7, 8, 12, 31, 128, 132, 256, 1024, 4096};
    for (size_t i = 0; i < tokens.size(); ++i) {
        if (reset_every > 0 && i % (size_t) reset_every == 0) {
            history.clear();
            old.clear();
        }
        history.push_back(tokens[i]);
        old.push_back(tokens[i]);
        for (int w : windows)
            check(history.looping(w) == reference(old, w), "incremental / reference disagreement");
    }
}

static volatile int sink = 0;
static void benchmark(const char* name, const std::vector<int>& tokens) {
    using Clock = std::chrono::steady_clock;
    std::vector<int> old;
    old.reserve(tokens.size());
    const auto begin = Clock::now();
    for (int t : tokens) {
        old.push_back(t);
        sink = reference(old, 1024);
    }
    const auto middle = Clock::now();
    LoopHistory history;
    for (int t : tokens) {
        history.push_back(t);
        sink = history.looping(1024);
    }
    const auto end = Clock::now();
    const double before = std::chrono::duration<double, std::milli>(middle - begin).count();
    const double after = std::chrono::duration<double, std::milli>(end - middle).count();
    std::printf("%s: tokens=%zu old_ms=%.3f new_ms=%.3f old_history_bytes=%zu new_history_bytes=%zu\n",
                name, tokens.size(), before, after, old.capacity() * sizeof(int), sizeof(history));
}

int main() {
    std::mt19937 random(20261022);
    std::vector<int> tokens;
    for (int alphabet : {1, 2, 17, 65536}) {
        tokens.clear();
        for (int i = 0; i < 12000; ++i) tokens.push_back((int) (random() % alphabet));
        differential(tokens);
        differential(tokens, 1031);   // clear after ring wrap and just beyond the answer window
    }
    for (int period = 1; period <= 40; ++period) {
        tokens.clear();
        for (int i = 0; i < 4200; ++i) tokens.push_back(i % period);
        tokens[2100] = -1;   // reject a broken period, then recover after it leaves the window
        differential(tokens);
    }
    LoopHistory history;
    for (int i = 0; i < 1000000; ++i) history.push_back(i % 32);
    check(history.looping(900000) == 32, "large configured window uses bounded storage");
    history.clear();
    check(history.looping(1024) == 0, "clear forgets prior comparisons");

    // Scheduler storage is reused without retaining a previous step's groups.
    std::vector<int> sizes;
    sizes.reserve(8);
    const auto* data = sizes.data();
    for (int active = 1; active <= 8; ++active)
        for (int ready = 0; ready <= active; ++ready)
            for (int cap = 1; cap <= 8; ++cap)
                for (bool even : {false, true}) {
                    strata::core::split_groups(ready, active, cap, even, sizes);
                    check(sizes == strata::core::split_groups(ready, active, cap, even), "group API equivalence");
                    check(sizes.data() == data, "scheduler groups reallocated after reserve");
                }
    std::puts("PASS: differential random, periods 1..40, window boundaries, clear, long stream, reusable groups");
    tokens.clear();
    for (int i = 0; i < 200000; ++i) tokens.push_back((int) (random() % 65536));
    benchmark("ordinary", tokens);
    for (int i = 0; i < (int) tokens.size(); ++i) tokens[(size_t) i] = i % 32;
    benchmark("repeated-period-32", tokens);
    std::fill(tokens.begin(), tokens.end(), 0);
    benchmark("repeated-period-1", tokens);
    return 0;
}
