// Host-only RAM slot state tracking. Caller holds the tier's existing mutex (or owns setup/prefill).
#pragma once
#include <algorithm>
#include <cstddef>
#include <numeric>
#include <vector>

namespace strata::core {
class DirtySlots {
public:
    struct Ref {
        DirtySlots* owner;
        size_t index;
        operator char() const { return owner->states_[index]; }
        Ref& operator=(char value) { owner->set(index, value); return *this; }
        Ref& operator=(const Ref& other) { return *this = char(other); }
    };
    void assign(size_t n, char value) {
        states_.assign(n, value);
        marked_.assign(n, 0);
        pending_.clear();
        pending_.reserve(n);
        free_ = value == 0 ? n : 0;
        touch_all();
    }
    Ref operator[](size_t i) { return {this, i}; }
    char operator[](size_t i) const { return states_[i]; }
    auto begin() const { return states_.begin(); }
    auto end() const { return states_.end(); }
    size_t size() const { return states_.size(); }
    size_t free_count() const { return free_; }
    bool marked(size_t i) const { return marked_[i] != 0; }
    void touch(size_t i) {
        if (i < marked_.size() && !marked_[i]) {
            marked_[i] = 1;
            pending_.push_back(int(i));
        }
    }
    void touch_all() { for (size_t i = 0; i < size(); ++i) touch(i); }
    // Clear marks before processing: mutations during maintenance are work for the next boundary.
    void take(std::vector<int>& out, bool full) {
        if (full) {
            out.resize(size());
            std::iota(out.begin(), out.end(), 0);
            std::fill(marked_.begin(), marked_.end(), 0);
        } else {
            out.assign(pending_.begin(), pending_.end());
            for (int i : out) marked_[size_t(i)] = 0;
            std::sort(out.begin(), out.end()); // preserve the legacy slot-order cleanup semantics
        }
        pending_.clear(); // keep each class's capacity; swapping a shared scratch would churn allocations
    }
private:
    void set(size_t i, char value) {
        free_ -= states_[i] == 0;
        states_[i] = value;
        free_ += value == 0;
        touch(i); // key may have changed even if the state did not
    }
    std::vector<char> states_;
    std::vector<unsigned char> marked_;
    std::vector<int> pending_;
    size_t free_ = 0;
};
} // namespace strata::core
