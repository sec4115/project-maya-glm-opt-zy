// GLM checkpoint retention: keep the earliest reusable prefix and rotate its leaves.
#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace strata::program::glm_cache_policy {

// Empty entries are reused first. With room for at least two states, protect the
// shortest valid checkpoint: later appends must not evict the shared prefix.
inline size_t victim(const size_t* lengths, const uint64_t* stamps, size_t n, bool pin_root) {
    if (n == 0) return 0;
    size_t root = 0;
    for (size_t i = 0; i < n; ++i) {
        if (lengths[i] == 0) return i;
        if (lengths[i] < lengths[root]) root = i;
    }
    size_t v = pin_root && n > 1 && root == 0 ? 1 : 0;
    for (size_t i = 0; i < n; ++i)
        if (!(pin_root && n > 1 && i == root) && stamps[i] < stamps[v]) v = i;
    return v;
}

// Bound the number of prompt checkpoints without discarding the system/user
// boundary merely because a long prompt also supplied many periodic positions.
inline void retain_marks(std::vector<size_t>& at, size_t cap, size_t root, bool pin_root) {
    if (at.size() <= cap) return;
    const bool keep = pin_root && cap >= 2 && std::binary_search(at.begin(), at.end(), root);
    if (!keep) {
        at.erase(at.begin(), at.end() - cap);
        return;
    }
    std::vector<size_t> selected{root};
    for (size_t i = at.size(); i-- > 0 && selected.size() < cap;)
        if (at[i] != root) selected.push_back(at[i]);
    std::sort(selected.begin(), selected.end());
    at.swap(selected);
}

}  // namespace strata::program::glm_cache_policy
