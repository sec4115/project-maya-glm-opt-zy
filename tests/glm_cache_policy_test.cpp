#include "strata/program/glm_cache_policy.hpp"

#include <cstdio>
#include <vector>

#define CHECK(c) do { if (!(c)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #c); return 1; } } while (false)

int main() {
    using namespace strata::program::glm_cache_policy;
    {
        const size_t lengths[] = {4096, 8192, 12288, 16384};
        const uint64_t stamps[] = {1, 2, 3, 4};
        CHECK(victim(lengths, stamps, 4, true) == 1);
        CHECK(victim(lengths, stamps, 4, false) == 0);
    }
    {
        const size_t lengths[] = {8192, 4096, 16384, 12288};
        const uint64_t stamps[] = {2, 1, 4, 3};
        CHECK(victim(lengths, stamps, 4, true) == 0);
        CHECK(victim(lengths, stamps, 4, false) == 1);
    }
    {
        const size_t lengths[] = {4096, 0, 16384};
        const uint64_t stamps[] = {1, 99, 2};
        CHECK(victim(lengths, stamps, 3, true) == 1);
        CHECK(victim(lengths, stamps, 1, true) == 0);
    }
    {
        std::vector<size_t> marks{4096, 16384, 32768, 49152, 65536, 81920};
        retain_marks(marks, 4, 4096, true);
        CHECK((marks == std::vector<size_t>{4096, 49152, 65536, 81920}));
        retain_marks(marks, 1, 4096, true);
        CHECK((marks == std::vector<size_t>{81920}));
        retain_marks(marks, 0, 4096, true);
        CHECK(marks.empty());
    }
    {
        std::vector<size_t> marks{4096, 16384, 32768, 49152, 65536};
        retain_marks(marks, 3, 16384, true);
        CHECK((marks == std::vector<size_t>{16384, 49152, 65536}));
    }
    std::puts("GLM cache retention policy: PASS");
}
