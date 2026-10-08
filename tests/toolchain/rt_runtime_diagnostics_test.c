/* Deterministic runtime tests: no FIFO threads, affinity changes, or hardware access. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "linuxinitialize.h"
#include <assert.h>
#include <setjmp.h>
#include <stdint.h>
#include <string.h>

static int test_clock_gettime(clockid_t clock, struct timespec *value);
static int test_clock_nanosleep(clockid_t clock, int flags, const struct timespec *deadline,
                               struct timespec *remaining);
static void test_pthread_exit(void *result) __attribute__((noreturn));
#define clock_gettime test_clock_gettime
#define clock_nanosleep test_clock_nanosleep
#define pthread_exit test_pthread_exit
#include "../../toolchain/simrt_linux_target/src/simrt_rt_runtime.c"
#undef clock_gettime
#undef clock_nanosleep
#undef pthread_exit

volatile boolean_T runModel = 1;
sem_t stopSem, baserateTaskSem;
pthread_t baseRateThread, schedulerThread;
static int64_t clock_values[16];
static size_t clock_count, clock_index;
static unsigned sleep_count, interrupt_sleeps;
static int stop_in_sleep, stop_at_clock, stopping, terminated;
static int64_t expected_sleep_deadline;
static jmp_buf stopped;

static int test_clock_gettime(clockid_t clock, struct timespec *value)
{
    int64_t current;
    assert(clock == CLOCK_MONOTONIC);
    assert(clock_index < clock_count);
    current = clock_values[clock_index++];
    value->tv_sec = (time_t)(current / INT64_C(1000000000));
    value->tv_nsec = (long)(current % INT64_C(1000000000));
    if (stop_at_clock && (int)clock_index == stop_at_clock) stop_signal = SIGTERM;
    return 0;
}

static int test_clock_nanosleep(clockid_t clock, int flags, const struct timespec *deadline,
                               struct timespec *remaining)
{
    assert(clock == CLOCK_MONOTONIC && flags == TIMER_ABSTIME && remaining == NULL);
    assert((int64_t)deadline->tv_sec * INT64_C(1000000000) + deadline->tv_nsec == expected_sleep_deadline);
    ++sleep_count;
    if (stop_in_sleep) stop_signal = SIGTERM;
    return stop_in_sleep || sleep_count <= interrupt_sleeps ? EINTR : 0;
}

static void test_pthread_exit(void *result)
{
    assert(result == NULL && stopping);
    longjmp(stopped, 1);
}

int __real_sem_wait(sem_t *semaphore) { (void)semaphore; assert(0); return -1; }
int __real_sem_post(sem_t *semaphore) { (void)semaphore; return 0; }
void exitFcn(int number) { assert(number == SIGTERM); runModel = 0; }
void *terminateTask(void *unused) { assert(unused == NULL); ++terminated; return NULL; }
void *baseRateTask(void *unused) { (void)unused; assert(0); return NULL; }

static void clocks(const int64_t *values, size_t count)
{
    assert(count <= sizeof(clock_values) / sizeof(clock_values[0]));
    memcpy(clock_values, values, count * sizeof(values[0]));
    clock_count = count;
    clock_index = 0;
}

#define CLOCKS(...) do { const int64_t values[] = {__VA_ARGS__}; clocks(values, sizeof(values) / sizeof(values[0])); } while (0)

static void reset_runtime(void)
{
    memset(&timing, 0, sizeof(timing));
    initialized = in_model_thread = 1;
    period_ns = 1000000;
    next_release_ns = 2000000;
    spin_us = 50;
    step_active = model_step_active = stop_signal = status_thread_started = 0;
    cycles = completed_cycles = deadline_misses = skipped_releases = 0;
    model_step_calls = model_step_completed_calls = model_step_interval_samples = 0;
    model_step_interval_min_ns = model_step_interval_max_ns = 0;
    previous_wake_latency_ns = previous_sleep_return_lateness_ns = 0;
    previous_sleep_performed = 0;
    sleep_count = interrupt_sleeps = 0;
    stop_in_sleep = stop_at_clock = stopping = terminated = 0;
    expected_sleep_deadline = 1950000;
    runModel = 1;
}

static void test_sleep_and_window_boundary(void)
{
    reset_runtime();
    interrupt_sleeps = 1;
    CLOCKS(1000000, 1000010, 1100000, 1960000, 2000000, 2001000, 2011000);
    assert(__wrap_sem_wait(&baserateTaskSem) == 0);
    simrt_rt_step_begin();
    simrt_rt_step_end();
    assert(clock_index == clock_count && sleep_count == 2 && timing.sleep_calls == 2);
    assert(timing.sleep_return_lateness_current_ns == 10000 && timing.wake_latency_max_ns == 0);
    assert(timing.release_lateness_current_ns == 1000 && timing.entry_delay_current_ns == 1000);
    CLOCKS(2012000, 2950000, 3000000, 3001000);
    assert(__wrap_sem_wait(&baserateTaskSem) == 0);
    simrt_rt_step_begin();
    assert(clock_index == clock_count && sleep_count == 2 && timing.sleep_skipped_count == 1);
    assert(timing.sleep_return_lateness_current_ns == 0 && !timing.sleep_performed);
    assert(model_step_interval_min_ns == 1000000 && model_step_interval_max_ns == 1000000);
}

static void test_interrupted_sleep_at_window(void)
{
    reset_runtime();
    interrupt_sleeps = 1;
    CLOCKS(1000000, 1000010, 1950000, 2000000);
    assert(__wrap_sem_wait(&baserateTaskSem) == 0);
    assert(clock_index == clock_count && sleep_count == 1 && timing.sleep_calls == 1);
    assert(timing.sleep_return_lateness_current_ns == 0 && timing.wake_latency_current_ns == 0);
}

static void test_late_then_short_interval(void)
{
    char json[2048];
    size_t length;
    FILE *file;
    reset_runtime();
    model_step_calls = cycles = 1;
    model_step_started_ns = started_ns = 1000000;
    CLOCKS(1010000, 1010010, 2196440, 2196440, 2206440);
    assert(__wrap_sem_wait(&baserateTaskSem) == 0);
    simrt_rt_step_begin();
    simrt_rt_step_end();
    assert(clock_index == clock_count && timing.interval_late_count == 1);
    assert(timing.sleep_return_lateness_current_ns == 246440);
    assert(timing.sleep_return_after_release_count == 1 && timing.wake_latency_max_ns == 196440);
    expected_sleep_deadline = 2950000;
    CLOCKS(2210000, 2210010, 2955000, 3000000, 3000000);
    assert(__wrap_sem_wait(&baserateTaskSem) == 0);
    simrt_rt_step_begin();
    assert(clock_index == clock_count && timing.interval_early_count == 1);
    assert(timing.last_outlier.interval_error_ns == -196440);
    assert(timing.last_outlier.previous_release_lateness_ns == 196440);
    assert(timing.last_outlier.previous_sleep_return_lateness_ns == 246440);
    assert(timing.last_outlier.previous_wake_latency_ns == 196440);
    assert(model_step_interval_min_ns == 803560 && model_step_interval_max_ns == 1196440);
    file = tmpfile();
    assert(file != NULL && write_timing_diagnostics(file, &timing) > 0);
    rewind(file);
    length = fread(json, 1, sizeof(json) - 1, file);
    json[length] = '\0';
    assert(fclose(file) == 0);
    assert(strstr(json, "\"model_step_interval_early_count\":1") != NULL);
    assert(strstr(json, "\"model_step_interval_late_count\":1") != NULL);
    assert(strstr(json, "\"interval_error_ns\":-196440") != NULL);
}

static void test_entry_delay_and_overrun(void)
{
    reset_runtime();
    spin_us = 500;
    cycles = model_step_calls = 1;
    release_ns = started_ns = model_step_started_ns = 1000000;
    step_active = 1;
    CLOCKS(3500000, 3500100, 4000000, 4050001);
    assert(__wrap_sem_wait(&baserateTaskSem) == 0);
    simrt_rt_step_begin();
    assert(clock_index == clock_count && sleep_count == 0 && timing.sleep_skipped_count == 1);
    assert(deadline_misses == 1 && skipped_releases == 2 && release_ns == 4000000);
    assert(timing.wake_latency_current_ns == 0 && timing.entry_delay_current_ns == 50001);
    assert(timing.release_lateness_max_ns == 50001 && timing.interval_late_count == 1);
    assert(model_step_interval_max_ns == 3050001);
}

static void test_counter_boundaries(void)
{
    const int64_t entries[] = {1050000, 2000000, 3050000, 4000000, 5050001, 6000000};
    size_t index;
    reset_runtime();
    for (index = 0; index < sizeof(entries) / sizeof(entries[0]); ++index) {
        release_ns = started_ns = (int64_t)(index + 1) * 1000000;
        cycles = index + 1;
        step_active = 1;
        CLOCKS(entries[index], entries[index] + 100);
        simrt_rt_step_begin();
        simrt_rt_step_end();
        assert(clock_index == clock_count);
        assert(timing.interval_late_count == (index >= 4 ? 1 : 0));
        assert(timing.interval_early_count == (index >= 5 ? 1 : 0));
    }
    assert(model_step_interval_min_ns == 949999 && model_step_interval_max_ns == 1050001);
    timing.interval_late_count = UINT64_MAX;
    release_ns = started_ns = 7000000;
    cycles = 7;
    CLOCKS(7050001, 7050101);
    simrt_rt_step_begin();
    simrt_rt_step_end();
    assert(timing.interval_late_count == UINT64_MAX);
}

static void test_stopping(int during_sleep)
{
    reset_runtime();
    stopping = 1;
    if (during_sleep) {
        stop_in_sleep = 1;
        CLOCKS(1000000, 1000010, 1100000);
    } else {
        stop_at_clock = 3;
        CLOCKS(1000000, 1960000, 1970000, 1970010);
    }
    if (setjmp(stopped) == 0) {
        __wrap_sem_wait(&baserateTaskSem);
        assert(0);
    }
    assert(clock_index == clock_count && terminated == 1 && runModel == 0);
    assert(cycles == 0 && model_step_calls == 0 && completed_cycles == 0);
    assert(timing.interval_early_count == 0 && timing.interval_late_count == 0);
}

int main(void)
{
    test_sleep_and_window_boundary();
    test_interrupted_sleep_at_window();
    test_late_then_short_interval();
    test_entry_delay_and_overrun();
    test_counter_boundaries();
    test_stopping(1);
    test_stopping(0);
    puts("{\"event\":\"simrt_rt_diagnostics_tests\",\"passed\":7}");
    return 0;
}
