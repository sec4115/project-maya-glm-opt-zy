#include "strata/core/expert_eviction.hpp"
#include "../src/core/glm_fast_state.hpp"
#include "strata/core/dirty_slots.hpp"
#include "strata/core/expert_pipeline.hpp"
#include <cstdio>
#include <cstdlib>
#include <random>

static void require(bool value, const char* why) {
    if (!value) { std::fprintf(stderr, "FAIL %s\n", why); std::exit(1); }
}
int main() {
    using namespace strata::core;
    require(colder_expert(ExpertEviction::lfru, 10, 0, 2, 99, 100), "LFRU age must affect ranking");
    require(!colder_expert(ExpertEviction::lfu, 10, 0, 2, 99, 100), "LFU remains distinct");
    require(colder_expert(ExpertEviction::lfru, 0, 3, 0, 4, 100), "equal scores use age");
    require(!colder_expert(ExpertEviction::lfru, 10, 100, 2, 99, 100), "current tick has finite denominator");

    std::mt19937 rng(20261030);
    strata::core::DirtySlots slots;
    slots.assign(113, 0);
    std::vector<char> oracle(113, 0);
    std::vector<int> changed;
    for (int round = 0; round < 1000; ++round) {
        slots.take(changed, round % 31 == 0);
        for (int i : changed) require(i >= 0 && i < 113, "queue bounds");
        require(std::is_sorted(changed.begin(), changed.end()), "legacy slot order");
        require(std::adjacent_find(changed.begin(), changed.end()) == changed.end(), "deduplication");
        for (int j = 0; j < 43; ++j) {
            const int i = rng() % 113;
            const char state = char(rng() % 8);
            slots[size_t(i)] = state;
            oracle[size_t(i)] = state;
            require(slots.marked(size_t(i)), "mutation tracking");
        }
        size_t free = 0;
        for (size_t i = 0; i < oracle.size(); ++i) {
            require(char(slots[i]) == oracle[i], "state equality");
            free += oracle[i] == 0;
        }
        require(free == slots.free_count(), "free count");
    }
    // Real production Workers implementation: both serial and concurrent dispatch, including one-thread pools.
    int cases = 0;
    for (bool concurrent : {false, true}) for (int threads : {1, 2, 4, 12}) {
        strata::core::glmfast::Workers pool(threads - 1, 100, {}, concurrent);
        for (int experts : {1, 2, 3, 8}) for (int parts : {1, 3, 7}) for (int rep = 0; rep < 12; ++rep) {
            constexpr int rows = 71;
            std::vector<int> gu(size_t(experts * rows), -1), q(gu.size(), -1), dn(gu.size(), -1);
            strata::core::expert_pipeline(pool, experts, parts,
                [&](int e, int p, int n) {
                    for (int r = rows * p / n; r < rows * (p + 1) / n; ++r) gu[size_t(e * rows + r)] = e * 97 + r;
                    if ((p + rep) % 3 == 0) std::this_thread::yield();
                },
                [&](int e) {
                    for (int r = 0; r < rows; ++r) {
                        require(gu[size_t(e * rows + r)] == e * 97 + r, "complete gate before quantization");
                        q[size_t(e * rows + r)] = gu[size_t(e * rows + r)] * 3;
                    }
                },
                [&](int e, int p, int n) {
                    for (int r = rows * p / n; r < rows * (p + 1) / n; ++r) {
                        require(q[size_t(e * rows + r)] == (e * 97 + r) * 3, "quantized data published before down");
                        dn[size_t(e * rows + r)] = q[size_t(e * rows + r)] + 5;
                    }
                });
            for (int e = 0; e < experts; ++e) for (int r = 0; r < rows; ++r)
                require(dn[size_t(e * rows + r)] == (e * 97 + r) * 3 + 5, "down output and coverage");
            ++cases;
        }
    }
    std::printf("PASS dirty states 1000 randomized rounds, CPU dependencies %d cases\n", cases);
}
