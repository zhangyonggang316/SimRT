#include "xcp_core.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <deque>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace {
thread_local char last_error[512] = {};
constexpr uint64_t max_capacity = 10000000;
constexpr uint64_t max_signals = 4096;

void require(bool condition, const char* message) {
    if (!condition) throw std::invalid_argument(message);
}

struct Ring {
    explicit Ring(uint64_t limit) : capacity(limit) {}
    uint64_t capacity;
    uint64_t sequence = 0;
    std::vector<xcp_point> points;
    std::deque<std::pair<uint64_t, double>> minima;
    std::deque<std::pair<uint64_t, double>> maxima;

    uint64_t size() const { return static_cast<uint64_t>(points.size()); }
    const xcp_point& at(uint64_t index) const {
        const uint64_t start = sequence >= capacity ? sequence % capacity : 0;
        return points[static_cast<size_t>((start + index) % capacity)];
    }
    void append(double time, double value) {
        if (points.size() < capacity) points.push_back({time, value});
        else points[static_cast<size_t>(sequence % capacity)] = {time, value};
        while (!minima.empty() && minima.back().second >= value) minima.pop_back();
        while (!maxima.empty() && maxima.back().second <= value) maxima.pop_back();
        minima.emplace_back(sequence, value);
        maxima.emplace_back(sequence, value);
        ++sequence;
        const auto first = sequence > capacity ? sequence - capacity : 0;
        while (minima.front().first < first) minima.pop_front();
        while (maxima.front().first < first) maxima.pop_front();
    }
    void clear() {
        sequence = 0;
        points.clear();
        minima.clear();
        maxima.clear();
    }
};

void plot_ring(const Ring& ring, uint64_t first, uint64_t end, uint64_t max_points,
               xcp_point* output, uint64_t capacity, uint64_t* written) {
    const auto size = end - first;
    require(capacity >= std::min(max_points, size), "Plot output capacity is too small");
    require(size == 0 || output != nullptr, "Missing plot output");
    *written = 0;
    const auto emit = [&](uint64_t index) { output[(*written)++] = ring.at(index); };
    if (size <= max_points) {
        for (auto index = first; index < end; ++index) emit(index);
        return;
    }
    if (max_points == 1) { emit(end - 1); return; }
    emit(first);
    if (max_points == 3) {
        auto extreme = first + 1;
        for (auto index = first + 2; index < end - 1; ++index)
            if (std::abs(ring.at(index).value) > std::abs(ring.at(extreme).value)) extreme = index;
        emit(extreme);
    } else if (max_points >= 4) {
        // Keep raw extrema and endpoint samples; never average away spikes.
        const uint64_t buckets = (max_points - 2) / 2;
        const auto interior = size - 2;
        for (uint64_t bucket = 0; bucket < buckets; ++bucket) {
            const auto begin = first + 1 + (bucket * interior) / buckets;
            const auto stop = first + 1 + ((bucket + 1) * interior) / buckets;
            auto low = begin;
            auto high = begin;
            for (auto index = begin + 1; index < stop; ++index) {
                if (ring.at(index).value < ring.at(low).value) low = index;
                if (ring.at(index).value > ring.at(high).value) high = index;
            }
            emit(std::min(low, high));
            if (low != high) emit(std::max(low, high));
        }
    }
    emit(end - 1);
}

struct Core {
    explicit Core(uint64_t limit) : capacity(limit) {}
    uint64_t capacity;
    std::mutex mutex;
    std::unordered_map<std::string, uint64_t> names;
    std::vector<Ring> rings;
    Ring& ring(uint64_t id) {
        require(id > 0 && id <= rings.size(), "Unknown signal id");
        return rings[static_cast<size_t>(id - 1)];
    }
};

std::mutex registry_mutex;
std::unordered_map<uint64_t, std::shared_ptr<Core>> registry;
uint64_t next_handle = 1;

std::shared_ptr<Core> core(uint64_t handle) {
    std::lock_guard<std::mutex> lock(registry_mutex);
    auto item = registry.find(handle);
    require(item != registry.end(), "Invalid or closed core handle");
    return item->second;
}

template <typename Function> int guarded(Function function) noexcept {
    try {
        last_error[0] = '\0';
        function();
        return 0;
    } catch (const std::exception& error) {
        // Error reporting must remain allocation-free even after bad_alloc.
        std::strncpy(last_error, error.what(), sizeof(last_error) - 1);
    } catch (...) {
        std::strncpy(last_error, "Unknown C++ core error", sizeof(last_error) - 1);
    }
    last_error[sizeof(last_error) - 1] = '\0';
    return -1;
}
}

uint32_t xcp_core_abi_version(void) { return 1; }
const char* xcp_core_last_error(void) { return last_error; }

int xcp_core_create(uint64_t capacity, uint64_t* handle) {
    return guarded([&] {
        require(handle != nullptr, "Missing handle output");
        *handle = 0;
        require(capacity > 0 && capacity <= max_capacity, "Capacity must be 1..10000000");
        auto instance = std::make_shared<Core>(capacity);
        std::lock_guard<std::mutex> lock(registry_mutex);
        require(next_handle != 0, "Core handle limit exhausted");
        const auto assigned = next_handle++;
        registry.emplace(assigned, std::move(instance));
        *handle = assigned;
    });
}

int xcp_core_destroy(uint64_t handle) {
    return guarded([&] {
        std::lock_guard<std::mutex> lock(registry_mutex);
        require(registry.erase(handle) == 1, "Invalid or closed core handle");
    });
}

int xcp_core_ensure_signal(uint64_t handle, const char* name, uint64_t* signal) {
    return guarded([&] {
        require(name != nullptr && signal != nullptr, "Missing signal name or output");
        const std::string key(name);
        require(!key.empty() && key.size() <= 1024, "Signal name must contain 1..1024 UTF-8 bytes");
        auto instance = core(handle);
        std::lock_guard<std::mutex> lock(instance->mutex);
        auto item = instance->names.find(key);
        if (item != instance->names.end()) { *signal = item->second; return; }
        require(instance->rings.size() < max_signals, "Signal limit exceeded (4096)");
        const auto id = static_cast<uint64_t>(instance->rings.size() + 1);
        instance->rings.emplace_back(instance->capacity);
        try { instance->names.emplace(key, id); }
        catch (...) { instance->rings.pop_back(); throw; }
        *signal = id;
    });
}

int xcp_core_append(uint64_t handle, const uint64_t* signals, const double* times,
                    const double* values, uint64_t count) {
    return guarded([&] {
        require(count == 0 || (signals && times && values), "Missing batch arrays");
        require(count <= 100000000, "Batch size exceeds 100000000 values");
        auto instance = core(handle);
        std::lock_guard<std::mutex> lock(instance->mutex);
        // Validate the complete batch before changing any ring, including order
        // between multiple values for the same signal in this batch.
        std::unordered_map<uint64_t, double> previous;
        for (uint64_t index = 0; index < count; ++index) {
            auto& ring = instance->ring(signals[index]);
            require(std::isfinite(times[index]) && times[index] >= 0,
                    "Timestamps must be finite and nonnegative");
            require(std::isfinite(values[index]), "Sample values must be finite");
            auto preceding = previous.find(signals[index]);
            const double last = preceding != previous.end() ? preceding->second :
                                (ring.size() ? ring.at(ring.size() - 1).elapsed_seconds : 0);
            require(times[index] >= last, "Timestamps must be nondecreasing per signal");
            previous[signals[index]] = times[index];
        }
        for (uint64_t index = 0; index < count; ++index)
            instance->ring(signals[index]).append(times[index], values[index]);
    });
}

int xcp_core_clear(uint64_t handle) {
    return guarded([&] {
        auto instance = core(handle);
        std::lock_guard<std::mutex> lock(instance->mutex);
        for (auto& ring : instance->rings) ring.clear();
    });
}

int xcp_core_total(uint64_t handle, uint64_t* count) {
    return guarded([&] {
        require(count != nullptr, "Missing count output");
        auto instance = core(handle);
        std::lock_guard<std::mutex> lock(instance->mutex);
        *count = 0;
        for (const auto& ring : instance->rings) *count += ring.size();
    });
}

int xcp_core_stats(uint64_t handle, uint64_t signal, xcp_stats* output) {
    return guarded([&] {
        require(output != nullptr, "Missing stats output");
        auto instance = core(handle);
        std::lock_guard<std::mutex> lock(instance->mutex);
        const auto& ring = instance->ring(signal);
        *output = {0, 0, 0, ring.size()};
        if (ring.size()) {
            output->latest = ring.at(ring.size() - 1).value;
            output->minimum = ring.minima.front().second;
            output->maximum = ring.maxima.front().second;
        }
    });
}

int xcp_core_snapshot(uint64_t handle, uint64_t signal, xcp_point* output,
                      uint64_t capacity, uint64_t* written) {
    return guarded([&] {
        require(written != nullptr, "Missing length output");
        auto instance = core(handle);
        std::lock_guard<std::mutex> lock(instance->mutex);
        const auto& ring = instance->ring(signal);
        *written = ring.size();
        require(capacity >= ring.size(), "Snapshot output capacity is too small");
        require(ring.size() == 0 || output != nullptr, "Missing snapshot output");
        for (uint64_t index = 0; index < ring.size(); ++index) output[index] = ring.at(index);
    });
}

int xcp_core_plot(uint64_t handle, uint64_t signal, uint64_t max_points,
                  xcp_point* output, uint64_t capacity, uint64_t* written) {
    return guarded([&] {
        require(written != nullptr && max_points > 0, "Plot budget must be positive");
        auto instance = core(handle);
        std::lock_guard<std::mutex> lock(instance->mutex);
        const auto& ring = instance->ring(signal);
        plot_ring(ring, 0, ring.size(), max_points, output, capacity, written);
    });
}

int xcp_core_plot_range(uint64_t handle, uint64_t signal, double first, double last,
                        uint64_t max_points, xcp_point* output, uint64_t capacity, uint64_t* written) {
    return guarded([&] {
        require(written != nullptr && max_points > 0, "Plot budget must be positive");
        require(std::isfinite(first) && std::isfinite(last) && first <= last, "Invalid plot time range");
        auto instance = core(handle);
        std::lock_guard<std::mutex> lock(instance->mutex);
        const auto& ring = instance->ring(signal);
        *written = 0;
        if (!ring.size() || last < ring.at(0).elapsed_seconds ||
            first > ring.at(ring.size() - 1).elapsed_seconds) return;
        const auto bound = [&](double time, bool upper) {
            uint64_t low = 0, high = ring.size();
            while (low < high) {
                const auto middle = low + (high - low) / 2;
                const auto stamp = ring.at(middle).elapsed_seconds;
                if (stamp < time || (upper && stamp == time)) low = middle + 1;
                else high = middle;
            }
            return low;
        };
        const auto begin = bound(first, false);
        const auto end = bound(last, true);
        plot_ring(ring, begin > 0 ? begin - 1 : 0, std::min(end + 1, ring.size()),
                  max_points, output, capacity, written);
    });
}

int xcp_core_value_at(uint64_t handle, uint64_t signal, double time,
                      double* value, int* found, int* interpolated) {
    return guarded([&] {
        require(value && found && interpolated, "Missing cursor output");
        require(std::isfinite(time), "Cursor timestamp must be finite");
        auto instance = core(handle);
        std::lock_guard<std::mutex> lock(instance->mutex);
        const auto& ring = instance->ring(signal);
        *found = 0;
        *interpolated = 0;
        *value = 0;
        if (!ring.size() || time < ring.at(0).elapsed_seconds ||
            time > ring.at(ring.size() - 1).elapsed_seconds) return;
        uint64_t low = 0;
        uint64_t high = ring.size();
        while (low < high) {
            const auto middle = low + (high - low) / 2;
            if (ring.at(middle).elapsed_seconds <= time) low = middle + 1;
            else high = middle;
        }
        const auto& left = ring.at(low - 1);
        *found = 1;
        if (left.elapsed_seconds == time || low == ring.size()) { *value = left.value; return; }
        const auto& right = ring.at(low);
        const double fraction = (time - left.elapsed_seconds) /
                                (right.elapsed_seconds - left.elapsed_seconds);
        // Weighted terms avoid overflowing the difference between finite extremes.
        *value = (1.0 - fraction) * left.value + fraction * right.value;
        *interpolated = 1;
    });
}
