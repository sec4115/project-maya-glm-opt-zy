#include "strata/core/prefill_cpu.hpp"
#include <cstdio>
int main() {
    using strata::core::prefill_cpu_eligible;
    if (prefill_cpu_eligible(true,true,.22,.26,64,0)) return 1;
    if (!prefill_cpu_eligible(true,true,.22,.26,64,512)) return 2;
    if (!prefill_cpu_eligible(true,true,.22,.26,512,512)) return 3;
    if (prefill_cpu_eligible(true,true,.22,.26,513,512)) return 4;
    if (!prefill_cpu_eligible(true,true,.22,4.8,16384,0)) return 5;
    if (prefill_cpu_eligible(false,true,.22,4.8,64,512)) return 6;
    if (prefill_cpu_eligible(true,false,.22,4.8,64,512)) return 7;
    if (prefill_cpu_eligible(true,true,0,.26,64,512)) return 8;
    if (prefill_cpu_eligible(true,true,.22,0,64,512)) return 9;
    if (prefill_cpu_eligible(true,true,.22,.26,0,512)) return 10;
    if (!prefill_cpu_eligible(true,true,.22,.26,1024,512,1.0)) return 11;
    if (prefill_cpu_eligible(true,true,.22,.26,1024,512,2.0)) return 12;
    if (!prefill_cpu_eligible(true,true,.22,.01,1024,0,0.0)) return 13;
    std::puts("prefill_cpu_test: PASS");
}
