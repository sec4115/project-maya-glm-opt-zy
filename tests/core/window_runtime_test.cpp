#include "strata/spec/window_runtime.hpp"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <limits>

using strata::spec::WindowRuntime;

static void check(bool ok, const char* message) {
    if (!ok) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    WindowRuntime costs;
    check(costs.cost_ms(0) == 0.0 && costs.cost_ms(8) == 0.0, "unmeasured lengths have no cost");
    for (int i = 0; i < 9; ++i) check(!costs.observe(2, 10.0), "stable warm-up does not force a probe");
    check(costs.cost_ms(2) == 10.0, "stable wall time is measured");
    check(!costs.observe(2, 10000.0), "one host stall does not force a probe");
    check(costs.cost_ms(2) == 10.0, "one host stall does not dominate cost");
    for (int i = 0; i < 9; ++i) costs.observe(2, 10.0);
    for (double bad : {0.0, -1.0, std::numeric_limits<double>::infinity(),
                       std::numeric_limits<double>::quiet_NaN()})
        check(!costs.observe(2, bad), "invalid timing is rejected");
    check(costs.cost_ms(2) == 10.0, "invalid timing cannot poison the median");
    check(!costs.observe(-1, 10.0) && !costs.observe(9, 10.0), "out-of-range length rejected");
    check(costs.cost_ms(-1) == 0.0 && costs.cost_ms(9) == 0.0, "out-of-range cost is absent");

    // Workload changes: the old EMA (weight 0.1 after warm-up) crosses the
    // throughput boundary later than the median. One draft commits 1.8 tokens
    // in 12 ms; two commit 2.4 tokens in 10 ms, then cost 30 ms after the shift.
    for (int i = 0; i < 9; ++i) costs.observe(1, 12.0);
    check(2.4 / costs.cost_ms(2) > 1.8 / costs.cost_ms(1), "short-context workload favours two drafts");
    bool shifted = false;
    double legacy = 10.0;
    for (int i = 0; i < 5; ++i) {
        shifted = costs.observe(2, 30.0) || shifted;
        legacy += (30.0 - legacy) / 10.0;
    }
    check(shifted, "sustained workload change requests an early neighbour probe");
    check(costs.cost_ms(2) == 30.0, "recent costs replace obsolete measurements");
    check(2.4 / costs.cost_ms(2) < 1.8 / costs.cost_ms(1), "changed workload favours one draft");
    check(costs.cost_ms(2) > legacy, "median catches up to sustained slowdown sooner than legacy EMA");
    for (int i = 0; i < 12; ++i) check(!costs.observe(2, 30.0), "stable new regime does not repeatedly request probes");
    check(costs.cost_ms(1) == 12.0, "length histories stay separate");

    WindowRuntime threshold;
    for (int i = 0; i < 9; ++i) threshold.observe(1, 10.0);
    for (int i = 0; i < 9; ++i) check(!threshold.observe(1, 12.0), "exactly 20 percent does not repeatedly probe");
    bool over_threshold = false;
    for (int i = 0; i < 5; ++i) over_threshold = threshold.observe(1, 12.1) || over_threshold;
    check(over_threshold, "a sustained change above the threshold triggers a probe");
    shifted = false;
    for (int i = 0; i < 5; ++i) shifted = costs.observe(2, 10.0) || shifted;
    check(shifted && costs.cost_ms(2) == 10.0, "sustained speed-up is detected too");
    check(2.4 / costs.cost_ms(2) > 1.8 / costs.cost_ms(1), "window can grow after recovery");

    WindowRuntime even;
    even.observe(0, 10.0);
    even.observe(0, 20.0);
    check(even.cost_ms(0) == 15.0, "two-sample probes use the even median");
    WindowRuntime huge;
    huge.observe(8, std::numeric_limits<double>::max());
    huge.observe(8, std::numeric_limits<double>::max());
    check(std::isfinite(huge.cost_ms(8)), "finite large samples cannot overflow an even median");
    for (int i = 0; i < 1000000; ++i) costs.observe(i % 9, 20.0 + i % 3);
    for (int i = 0; i < 9; ++i) check(std::isfinite(costs.cost_ms(i)), "long stream stays bounded and finite");
    std::printf("PASS: stable/outlier/invalid/shift/recovery/independent lengths; state=%zu bytes\n", sizeof(costs));
}
