/* Opt-in 1/10/100 ms, single-task Linux runtime for the generated R2024b main. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "linuxinitialize.h"
#include "rtwtypes.h"
#include "MW_custom_RTOS_header.h"
#include <inttypes.h>
#include <fcntl.h>
#include <limits.h>
#include <math.h>
#include <stdatomic.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#if (MT != 0) || (MW_NUMBER_SUBRATES != 0) || (MW_IS_CONCURRENT != 0)
#error "SimRT RT requires single-task code generation, including for multirate models"
#endif
#if (MW_NUMBER_APERIODIC_TASKS > 0) || (MW_NUMBER_TIMER_DRIVEN_TASKS > 0)
#error "SimRT RT does not support asynchronous or independently scheduled tasks"
#endif
#if defined(MW_SOC_ENABLED) || defined(MW_SCHEDULE_TASK_WITH_ALSA_AUDIO) || defined(MW_NEEDS_BACKGROUND_TASK)
#error "SimRT RT does not support auxiliary scheduler/background task configurations"
#endif

#define THREAD_STACK_BYTES (1024U * 1024U)
#define INTERVAL_TOLERANCE_NS INT64_C(50000)

extern volatile boolean_T runModel;
extern int __real_sem_wait(sem_t *semaphore);
extern int __real_sem_post(sem_t *semaphore);

static volatile sig_atomic_t stop_signal;
static __thread int in_model_thread;
static int initialized;
static int report_written;
static int configured_cpu;
static int configured_priority;
static int affinity_prepared;
static cpu_set_t runtime_allowed, background_cpus;
static int latency_descriptor = -1;
static int spin_us;
static void release_latency_request(void);
static int realtime_kernel;
static int kernel_required;
static int step_active;
static int final_includes_termination;
static int64_t period_ns;
static int64_t next_release_ns;
static int64_t release_ns;
static int64_t started_ns;
static int64_t first_release_ns;
static int64_t last_finished_ns;
static uint64_t cycles;
static uint64_t completed_cycles;
static uint64_t skipped_releases;
static uint64_t deadline_misses;
static uint64_t execution_max_ns;
static uint64_t cycle_interval_samples;
static uint64_t cycle_interval_min_ns;
static uint64_t cycle_interval_max_ns;
static long double wake_total_ns;
static long double execution_total_ns;
static long double cycle_interval_total_ns;
static int model_step_active;
static int64_t model_step_started_ns;
static uint64_t model_step_calls;
static uint64_t model_step_completed_calls;
static uint64_t model_step_interval_samples;
static uint64_t model_step_interval_min_ns;
static uint64_t model_step_interval_max_ns;
static uint64_t model_step_execution_min_ns;
static uint64_t model_step_execution_max_ns;
static uint64_t model_step_execution_current_ns;
static long double model_step_interval_total_ns;
static long double model_step_execution_total_ns;

typedef struct {
    uint64_t cycle;
    int64_t monotonic_ns;
    int64_t interval_error_ns;
    uint64_t release_lateness_ns;
    uint64_t previous_release_lateness_ns;
    uint64_t wake_latency_ns;
    uint64_t previous_wake_latency_ns;
    uint64_t sleep_return_lateness_ns;
    uint64_t previous_sleep_return_lateness_ns;
    int sleep_performed;
    int previous_sleep_performed;
} interval_outlier_t;

typedef struct {
    uint64_t interval_early_count;
    uint64_t interval_late_count;
    uint64_t release_lateness_current_ns;
    uint64_t release_lateness_max_ns;
    uint64_t entry_delay_current_ns;
    uint64_t entry_delay_max_ns;
    uint64_t wake_latency_current_ns;
    uint64_t wake_latency_max_ns;
    uint64_t sleep_return_lateness_current_ns;
    uint64_t sleep_return_lateness_max_ns;
    uint64_t sleep_calls;
    uint64_t sleep_skipped_count;
    uint64_t sleep_return_after_release_count;
    int sleep_performed;
    interval_outlier_t last_outlier;
} timing_diagnostics_t;

static timing_diagnostics_t timing;
static uint64_t previous_wake_latency_ns;
static uint64_t previous_sleep_return_lateness_ns;
static int previous_sleep_performed;

typedef struct {
    int64_t sampled_ns;
    int64_t elapsed_ns;
    uint64_t calls;
    uint64_t completed_calls;
    uint64_t interval_min_ns;
    uint64_t interval_max_ns;
    long double interval_mean_ns;
    uint64_t execution_current_ns;
    uint64_t execution_max_ns;
    uint64_t deadline_misses;
    uint64_t skipped_releases;
    timing_diagnostics_t timing;
} status_snapshot_t;

static atomic_flag status_lock = ATOMIC_FLAG_INIT;
static status_snapshot_t status_snapshot;
static pthread_t status_thread;
static pthread_mutex_t status_wait_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t status_wait_condition;
static int status_thread_started;
static int status_stop;
static int status_warning_written;
static int64_t status_next_publish_ns;
static double status_stop_time_seconds = -1.0;
static char status_path[PATH_MAX];

#define SIMRT_STRINGIFY_INNER(value) #value
#define SIMRT_STRINGIFY(value) SIMRT_STRINGIFY_INNER(value)
#ifdef MODEL
#define STATUS_MODEL_NAME SIMRT_STRINGIFY(MODEL)
#else
#define STATUS_MODEL_NAME "runtime_harness"
#endif

static void fail(const char *operation, int code)
{
    fprintf(stderr, "SimRT RT initialization/runtime failure: %s: %s (%d)\n",
            operation, strerror(code), code);
    fflush(stderr);
    exit(EXIT_FAILURE);
}

static void require_zero(int status, const char *operation)
{
    if (status != 0) {
        fail(operation, status);
    }
}

static int64_t now_ns(void)
{
    struct timespec time;
    if (clock_gettime(CLOCK_MONOTONIC, &time) != 0) {
        fail("clock_gettime", errno);
    }
    return (int64_t)time.tv_sec * INT64_C(1000000000) + time.tv_nsec;
}

static uint64_t saturating_add(uint64_t left, uint64_t right)
{
    return UINT64_MAX - left < right ? UINT64_MAX : left + right;
}

void simrt_rt_set_stop_time(double seconds)
{
    if (initialized) {
        fail("stop time must be configured before runtime initialization", EINVAL);
    }
    status_stop_time_seconds = isfinite(seconds) && seconds >= 0.0 ? seconds : -1.0;
}

static status_snapshot_t capture_status(int64_t sampled_ns)
{
    status_snapshot_t snapshot;
    snapshot.sampled_ns = sampled_ns;
    snapshot.elapsed_ns = cycles ? sampled_ns - first_release_ns : 0;
    snapshot.calls = model_step_calls;
    snapshot.completed_calls = model_step_completed_calls;
    snapshot.interval_min_ns = model_step_interval_min_ns;
    snapshot.interval_max_ns = model_step_interval_max_ns;
    snapshot.interval_mean_ns = model_step_interval_samples
        ? model_step_interval_total_ns / model_step_interval_samples : 0.0L;
    snapshot.execution_current_ns = model_step_execution_current_ns;
    snapshot.execution_max_ns = model_step_execution_max_ns;
    snapshot.deadline_misses = deadline_misses;
    snapshot.skipped_releases = skipped_releases;
    snapshot.timing = timing;
    return snapshot;
}

static int write_timing_diagnostics(FILE *file, const timing_diagnostics_t *diagnostics)
{
    const interval_outlier_t *outlier = &diagnostics->last_outlier;
    if (fprintf(file,
        ",\"interval_tolerance_ns\":%" PRId64 ","
        "\"model_step_interval_early_count\":%" PRIu64 ","
        "\"model_step_interval_late_count\":%" PRIu64 ","
        "\"model_step_release_lateness_current_ns\":%" PRIu64 ","
        "\"model_step_release_lateness_max_ns\":%" PRIu64 ","
        "\"model_step_entry_delay_current_ns\":%" PRIu64 ","
        "\"model_step_entry_delay_max_ns\":%" PRIu64 ","
        "\"wake_latency_current_ns\":%" PRIu64 ",\"wake_latency_max_ns\":%" PRIu64 ","
        "\"sleep_return_lateness_current_ns\":%" PRIu64 ","
        "\"sleep_return_lateness_max_ns\":%" PRIu64 ","
        "\"sleep_calls\":%" PRIu64 ",\"sleep_skipped_count\":%" PRIu64 ","
        "\"sleep_return_after_release_count\":%" PRIu64 ",\"sleep_performed\":%s,"
        "\"last_interval_outlier\":",
        INTERVAL_TOLERANCE_NS, diagnostics->interval_early_count, diagnostics->interval_late_count,
        diagnostics->release_lateness_current_ns, diagnostics->release_lateness_max_ns,
        diagnostics->entry_delay_current_ns, diagnostics->entry_delay_max_ns,
        diagnostics->wake_latency_current_ns, diagnostics->wake_latency_max_ns,
        diagnostics->sleep_return_lateness_current_ns, diagnostics->sleep_return_lateness_max_ns,
        diagnostics->sleep_calls, diagnostics->sleep_skipped_count,
        diagnostics->sleep_return_after_release_count, diagnostics->sleep_performed ? "true" : "false") < 0) {
        return -1;
    }
    if (!outlier->cycle) {
        return fputs("null", file);
    }
    return fprintf(file,
        "{\"cycle\":%" PRIu64 ",\"monotonic_ns\":%" PRId64 ","
        "\"interval_error_ns\":%" PRId64 ",\"release_lateness_ns\":%" PRIu64 ","
        "\"previous_release_lateness_ns\":%" PRIu64 ","
        "\"wake_latency_ns\":%" PRIu64 ",\"previous_wake_latency_ns\":%" PRIu64 ","
        "\"sleep_return_lateness_ns\":%" PRIu64 ","
        "\"previous_sleep_return_lateness_ns\":%" PRIu64 ","
        "\"sleep_performed\":%s,\"previous_sleep_performed\":%s}",
        outlier->cycle, outlier->monotonic_ns, outlier->interval_error_ns,
        outlier->release_lateness_ns, outlier->previous_release_lateness_ns,
        outlier->wake_latency_ns, outlier->previous_wake_latency_ns,
        outlier->sleep_return_lateness_ns, outlier->previous_sleep_return_lateness_ns,
        outlier->sleep_performed ? "true" : "false",
        outlier->previous_sleep_performed ? "true" : "false");
}

/* The FIFO thread only attempts a bounded copy, and never waits for the writer. */
static void publish_status(int64_t sampled_ns)
{
    if (!status_thread_started || sampled_ns < status_next_publish_ns) {
        return;
    }
    status_next_publish_ns = sampled_ns + INT64_C(100000000);
    if (!atomic_flag_test_and_set_explicit(&status_lock, memory_order_acquire)) {
        status_snapshot = capture_status(sampled_ns);
        atomic_flag_clear_explicit(&status_lock, memory_order_release);
    }
}

static void status_warning(int code)
{
    if (!status_warning_written) {
        fprintf(stderr, "SimRT RT live status unavailable: %s (%d)\n", strerror(code), code);
        status_warning_written = 1;
    }
}

static void write_status(const status_snapshot_t *snapshot, const char *state)
{
    char temporary[PATH_MAX + 16];
    char stop_time[64];
    struct timespec updated;
    FILE *file;
    int descriptor, failure = 0;
    int64_t updated_ns;
    if (clock_gettime(CLOCK_REALTIME, &updated) != 0) {
        status_warning(errno);
        return;
    }
    updated_ns = (int64_t)updated.tv_sec * INT64_C(1000000000) + updated.tv_nsec;
    if (status_stop_time_seconds >= 0.0) {
        snprintf(stop_time, sizeof(stop_time), "%.17g", status_stop_time_seconds);
    } else {
        strcpy(stop_time, "null");
    }
    snprintf(temporary, sizeof(temporary), "%s.tmp.XXXXXX", status_path);
    descriptor = mkstemp(temporary);
    if (descriptor < 0) {
        status_warning(errno);
        return;
    }
    file = fdopen(descriptor, "w");
    if (file == NULL) {
        failure = errno;
        close(descriptor);
    } else {
        if (fprintf(file,
            "{\"schema_version\":1,\"event\":\"simrt_status\",\"model\":\"%s\","
            "\"pid\":%ld,\"state\":\"%s\",\"updated_unix_ns\":%" PRId64 ","
            "\"sample_monotonic_ns\":%" PRId64 ",\"elapsed_ns\":%" PRId64 ","
            "\"period_ns\":%" PRId64 ",\"cpu\":%d,\"priority\":%d,"
            "\"cpu_dma_latency_active\":%s,\"spin_us\":%d,"
            "\"realtime_kernel\":%s,\"memory_locked\":true,\"stop_time_seconds\":%s,"
            "\"model_step_calls\":%" PRIu64 ",\"model_step_completed_calls\":%" PRIu64 ","
            "\"model_step_interval_min_ns\":%" PRIu64 ","
            "\"model_step_interval_mean_ns\":%.3Lf,\"model_step_interval_max_ns\":%" PRIu64 ","
            "\"model_step_execution_current_ns\":%" PRIu64 ","
            "\"model_step_execution_max_ns\":%" PRIu64 ","
            "\"deadline_misses\":%" PRIu64 ",\"skipped_releases\":%" PRIu64,
            STATUS_MODEL_NAME, (long)getpid(), state, updated_ns,
            snapshot->sampled_ns, snapshot->elapsed_ns, period_ns,
            configured_cpu, configured_priority, latency_descriptor >= 0 ? "true" : "false", spin_us,
            realtime_kernel ? "true" : "false", stop_time,
            snapshot->calls, snapshot->completed_calls, snapshot->interval_min_ns,
            snapshot->interval_mean_ns, snapshot->interval_max_ns,
            snapshot->execution_current_ns, snapshot->execution_max_ns,
            snapshot->deadline_misses, snapshot->skipped_releases) < 0 ||
            write_timing_diagnostics(file, &snapshot->timing) < 0 || fputs("}\n", file) < 0) {
            failure = errno ? errno : EIO;
        }
        if (fclose(file) != 0 && !failure) {
            failure = errno ? errno : EIO;
        }
    }
    if (!failure && rename(temporary, status_path) != 0) {
        failure = errno;
    }
    if (failure) {
        unlink(temporary);
        status_warning(failure);
    }
}

static void *status_entry(void *unused)
{
    (void)unused;
    for (;;) {
        status_snapshot_t snapshot;
        struct timespec deadline;
        int stopped;
        if (!atomic_flag_test_and_set_explicit(&status_lock, memory_order_acquire)) {
            snapshot = status_snapshot;
            atomic_flag_clear_explicit(&status_lock, memory_order_release);
            write_status(&snapshot, "RUNNING");
        }
        if (clock_gettime(CLOCK_MONOTONIC, &deadline) != 0) {
            status_warning(errno);
            break;
        }
        ++deadline.tv_sec;
        pthread_mutex_lock(&status_wait_mutex);
        while (!status_stop) {
            int result = pthread_cond_timedwait(&status_wait_condition, &status_wait_mutex, &deadline);
            if (result != 0) {
                break;
            }
        }
        stopped = status_stop;
        pthread_mutex_unlock(&status_wait_mutex);
        if (stopped) {
            break;
        }
    }
    return NULL;
}

static void start_status_thread(void)
{
    pthread_attr_t attributes;
    pthread_condattr_t clock_attributes;
    struct sched_param priority = {0};
    ssize_t length = readlink("/proc/self/exe", status_path,
                              sizeof(status_path) - sizeof(".simrt-status.json"));
    int result;
    if (length < 0 || (size_t)length >= sizeof(status_path) - sizeof(".simrt-status.json")) {
        status_warning(length < 0 ? errno : ENAMETOOLONG);
        return;
    }
    status_path[length] = '\0';
    strcat(status_path, ".simrt-status.json");
    status_snapshot = capture_status(now_ns());
    result = pthread_condattr_init(&clock_attributes);
    if (result != 0) {
        status_warning(result);
        return;
    }
    result = pthread_condattr_setclock(&clock_attributes, CLOCK_MONOTONIC);
    if (result == 0) {
        result = pthread_cond_init(&status_wait_condition, &clock_attributes);
    }
    pthread_condattr_destroy(&clock_attributes);
    if (result != 0) {
        status_warning(result);
        return;
    }
    result = pthread_attr_init(&attributes);
    if (result != 0) {
        pthread_cond_destroy(&status_wait_condition);
        status_warning(result);
        return;
    }
    if ((result = pthread_attr_setstacksize(&attributes, THREAD_STACK_BYTES)) == 0 &&
        (result = pthread_attr_setinheritsched(&attributes, PTHREAD_EXPLICIT_SCHED)) == 0 &&
        (result = pthread_attr_setschedpolicy(&attributes, SCHED_OTHER)) == 0 &&
        (result = pthread_attr_setschedparam(&attributes, &priority)) == 0 &&
        (result = pthread_attr_setaffinity_np(&attributes, sizeof(background_cpus), &background_cpus)) == 0) {
        result = pthread_create(&status_thread, &attributes, status_entry, NULL);
    }
    pthread_attr_destroy(&attributes);
    if (result != 0) {
        pthread_cond_destroy(&status_wait_condition);
        status_warning(result);
        return;
    }
    status_thread_started = 1;
}

static void finish_status_thread(void)
{
    status_snapshot_t final_snapshot;
    if (!status_thread_started) {
        return;
    }
    pthread_mutex_lock(&status_wait_mutex);
    status_stop = 1;
    pthread_cond_signal(&status_wait_condition);
    pthread_mutex_unlock(&status_wait_mutex);
    require_zero(pthread_join(status_thread, NULL), "pthread_join live status");
    pthread_cond_destroy(&status_wait_condition);
    final_snapshot = capture_status(last_finished_ns);
    write_status(&final_snapshot, "STOPPED");
}

int64_t simrt_rt_period_ns(double period_seconds)
{
    if (period_seconds == 0.001) {
        return INT64_C(1000000);
    }
    if (period_seconds == 0.01) {
        return INT64_C(10000000);
    }
    if (period_seconds == 0.1) {
        return INT64_C(100000000);
    }
    return -1;
}

int simrt_rt_interval_outlier(int64_t interval, int64_t period)
{
    int64_t error = interval - period;
    if (error < -INTERVAL_TOLERANCE_NS) return -1;
    return error > INTERVAL_TOLERANCE_NS ? 1 : 0;
}

int64_t simrt_rt_sleep_deadline_ns(int64_t release, int configured_spin_us)
{
    int64_t tail;
    if (release < 0 || configured_spin_us < 0 || configured_spin_us > 500) {
        return -1;
    }
    tail = (int64_t)configured_spin_us * 1000;
    return release > tail ? release - tail : 0;
}

void simrt_rt_step_begin(void)
{
    int64_t current;
    uint64_t release_lateness, entry_delay;
    if (!initialized || !in_model_thread || !step_active || model_step_active) {
        fail("model_step begin outside an active model release", EINVAL);
    }
    current = now_ns();
    release_lateness = (uint64_t)(current - release_ns);
    entry_delay = (uint64_t)(current - started_ns);
    if (model_step_calls > 0) {
        uint64_t interval = (uint64_t)(current - model_step_started_ns);
        int outlier = simrt_rt_interval_outlier((int64_t)interval, period_ns);
        if (model_step_interval_samples == 0 || interval < model_step_interval_min_ns) {
            model_step_interval_min_ns = interval;
        }
        if (interval > model_step_interval_max_ns) {
            model_step_interval_max_ns = interval;
        }
        model_step_interval_samples = saturating_add(model_step_interval_samples, 1);
        model_step_interval_total_ns += (long double)interval;
        if (outlier != 0) {
            interval_outlier_t *record = &timing.last_outlier;
            if (outlier < 0) {
                timing.interval_early_count = saturating_add(timing.interval_early_count, 1);
            } else {
                timing.interval_late_count = saturating_add(timing.interval_late_count, 1);
            }
            record->cycle = cycles;
            record->monotonic_ns = current;
            record->interval_error_ns = (int64_t)interval - period_ns;
            record->release_lateness_ns = release_lateness;
            record->previous_release_lateness_ns = timing.release_lateness_current_ns;
            record->wake_latency_ns = timing.wake_latency_current_ns;
            record->previous_wake_latency_ns = previous_wake_latency_ns;
            record->sleep_return_lateness_ns = timing.sleep_return_lateness_current_ns;
            record->previous_sleep_return_lateness_ns = previous_sleep_return_lateness_ns;
            record->sleep_performed = timing.sleep_performed;
            record->previous_sleep_performed = previous_sleep_performed;
        }
    }
    timing.release_lateness_current_ns = release_lateness;
    if (release_lateness > timing.release_lateness_max_ns) timing.release_lateness_max_ns = release_lateness;
    timing.entry_delay_current_ns = entry_delay;
    if (entry_delay > timing.entry_delay_max_ns) timing.entry_delay_max_ns = entry_delay;
    previous_wake_latency_ns = timing.wake_latency_current_ns;
    previous_sleep_return_lateness_ns = timing.sleep_return_lateness_current_ns;
    previous_sleep_performed = timing.sleep_performed;
    model_step_started_ns = current;
    model_step_calls = saturating_add(model_step_calls, 1);
    model_step_active = 1;
}

void simrt_rt_step_end(void)
{
    int64_t current = now_ns();
    uint64_t elapsed;
    if (!initialized || !in_model_thread || !model_step_active) {
        fail("model_step end without a matching begin", EINVAL);
    }
    elapsed = (uint64_t)(current - model_step_started_ns);
    if (model_step_completed_calls == 0 || elapsed < model_step_execution_min_ns) {
        model_step_execution_min_ns = elapsed;
    }
    if (elapsed > model_step_execution_max_ns) {
        model_step_execution_max_ns = elapsed;
    }
    model_step_execution_total_ns += (long double)elapsed;
    model_step_execution_current_ns = elapsed;
    model_step_completed_calls = saturating_add(model_step_completed_calls, 1);
    model_step_active = 0;
}

/* Advance directly to a future release. Missed periods never become a semaphore backlog. */
int64_t simrt_rt_next_future_release(int64_t scheduled, int64_t now, int64_t period,
                                    uint64_t *skipped)
{
    if (period <= 0 || scheduled < 0 || now < 0 || skipped == NULL) {
        return -1;
    }
    if (now >= scheduled) {
        uint64_t count = (uint64_t)((now - scheduled) / period) + 1U;
        if (count > (uint64_t)((INT64_MAX - scheduled) / period)) {
            return -1;
        }
        scheduled += (int64_t)count * period;
        *skipped = saturating_add(*skipped, count);
    }
    return scheduled;
}

static int environment_integer(const char *name, int fallback, int minimum, int maximum)
{
    const char *text = getenv(name);
    char *end;
    long value;
    if (text == NULL) {
        return fallback;
    }
    errno = 0;
    value = strtol(text, &end, 10);
    if (errno != 0 || text == end || *end != '\0' || value < minimum || value > maximum) {
        fail(name, EINVAL);
    }
    return (int)value;
}

static int read_cpu_set(const char *path, cpu_set_t *cpus)
{
    FILE *file = fopen(path, "r");
    int first, last, separator, index;
    CPU_ZERO(cpus);
    if (file == NULL) return 0;
    while (fscanf(file, "%d", &first) == 1) {
        last = first;
        separator = fgetc(file);
        if (separator == '-') {
            if (fscanf(file, "%d", &last) != 1) break;
            separator = fgetc(file);
        }
        if (first < 0 || last < first || last >= CPU_SETSIZE) break;
        for (index = first; index <= last; ++index) CPU_SET(index, cpus);
        if (separator == '\n' || separator == EOF) {
            fclose(file);
            return 1;
        }
        if (separator != ',') break;
    }
    fclose(file);
    CPU_ZERO(cpus);
    return 0;
}

/* Run initialization/XCP workers on other physical cores, before they spawn. */
void simrt_rt_prepare(void)
{
    int index, default_cpu = -1;
    char path[160];
    cpu_set_t siblings, isolated, online;
    if (affinity_prepared) {
        return;
    }
    if (sched_getaffinity(0, sizeof(runtime_allowed), &runtime_allowed) != 0) {
        fail("sched_getaffinity", errno);
    }
    read_cpu_set("/sys/devices/system/cpu/isolated", &isolated);
    read_cpu_set("/sys/devices/system/cpu/online", &online);
    if (getenv("SIMRT_RT_CPU") == NULL) {
        cpu_set_t requested = runtime_allowed;
        for (index = 0; index < CPU_SETSIZE; ++index) {
            if (CPU_ISSET(index, &isolated) && CPU_ISSET(index, &online)) CPU_SET(index, &requested);
        }
        if (!CPU_EQUAL(&requested, &runtime_allowed)) {
            /* Probe every isolated candidate; the kernel intersects the cgroup cpuset. */
            if (sched_setaffinity(0, sizeof(requested), &requested) != 0 ||
                sched_getaffinity(0, sizeof(runtime_allowed), &runtime_allowed) != 0) {
                fail("cannot discover allowed isolated model CPUs", errno);
            }
        }
    }
    for (index = 0; index < CPU_SETSIZE; ++index) {
        if (CPU_ISSET(index, &runtime_allowed)) {
            default_cpu = index;
        }
    }
    for (index = 0; index < CPU_SETSIZE; ++index) {
        if (CPU_ISSET(index, &isolated) && CPU_ISSET(index, &online) &&
            CPU_ISSET(index, &runtime_allowed)) default_cpu = index;
    }
    configured_cpu = environment_integer("SIMRT_RT_CPU", default_cpu, 0, CPU_SETSIZE - 1);
    if (configured_cpu < 0) {
        fail("no allowed model CPU", EINVAL);
    }
    if (!CPU_ISSET(configured_cpu, &runtime_allowed) && CPU_ISSET(configured_cpu, &isolated) &&
        CPU_ISSET(configured_cpu, &online)) {
        /* nohz_full boot excludes isolated CPUs from inherited SSH affinity. */
        cpu_set_t requested = runtime_allowed;
        CPU_SET(configured_cpu, &requested);
        if (sched_setaffinity(0, sizeof(requested), &requested) != 0 ||
            sched_getaffinity(0, sizeof(runtime_allowed), &runtime_allowed) != 0) {
            fail("cannot include the isolated model CPU", errno);
        }
        /* sched_setaffinity may silently intersect a restrictive cgroup cpuset. */
        if (!CPU_ISSET(configured_cpu, &runtime_allowed)) {
            fail("isolated model CPU is excluded by the cgroup cpuset", EINVAL);
        }
    }
    if (!CPU_ISSET(configured_cpu, &runtime_allowed)) {
        fail("SIMRT_RT_CPU is not in the allowed affinity mask", EINVAL);
    }
    snprintf(path, sizeof(path), "/sys/devices/system/cpu/cpu%d/topology/thread_siblings_list", configured_cpu);
    if (!read_cpu_set(path, &siblings)) {
        fprintf(stderr, "SimRT RT: cannot read CPU%d SMT topology; only the model CPU is excluded from background work\n",
                configured_cpu);
    }
    CPU_SET(configured_cpu, &siblings);
    background_cpus = runtime_allowed;
    for (index = 0; index < CPU_SETSIZE; ++index) {
        if (CPU_ISSET(index, &siblings)) CPU_CLR(index, &background_cpus);
    }
    if (CPU_COUNT(&background_cpus) == 0) {
        background_cpus = runtime_allowed;
        if (CPU_COUNT(&background_cpus) > 1) CPU_CLR(configured_cpu, &background_cpus);
        fprintf(stderr, "SimRT RT: no separate physical core available for background work\n");
    }
    if (sched_setaffinity(0, sizeof(background_cpus), &background_cpus) != 0) {
        fail("background sched_setaffinity", errno);
    }
    affinity_prepared = 1;
}

static void release_latency_request(void)
{
    if (latency_descriptor >= 0) {
        close(latency_descriptor);
        latency_descriptor = -1;
    }
}

static void request_low_latency(void)
{
    int32_t latency = 0;
    latency_descriptor = open("/dev/cpu_dma_latency", O_WRONLY | O_CLOEXEC);
    if (latency_descriptor < 0 || write(latency_descriptor, &latency, sizeof(latency)) != sizeof(latency)) {
        int error = errno;
        release_latency_request();
        fprintf(stderr, "SimRT RT: CPU idle latency request unavailable: %s\n", strerror(error));
        return;
    }
    atexit(release_latency_request);
}

static int is_realtime_kernel(void)
{
    FILE *file = fopen("/sys/kernel/realtime", "r");
    int value = 0;
    if (file != NULL) {
        if (fscanf(file, "%d", &value) != 1) {
            value = 0;
        }
        fclose(file);
    }
    return value == 1;
}

static void finish_step(int64_t finished)
{
    uint64_t elapsed;
    if (!step_active) {
        return;
    }
    elapsed = (uint64_t)(finished - started_ns);
    completed_cycles = saturating_add(completed_cycles, 1);
    execution_total_ns += (long double)elapsed;
    if (elapsed > execution_max_ns) {
        execution_max_ns = elapsed;
    }
    if (finished > release_ns + period_ns) {
        deadline_misses = saturating_add(deadline_misses, 1);
    }
    last_finished_ns = finished;
    step_active = 0;
    publish_status(finished);
}

static void report(void)
{
    if (report_written) {
        return;
    }
    report_written = 1;
    printf("{\"event\":\"simrt_rt_summary\",\"period_ns\":%" PRId64 ","
           "\"realtime_kernel\":%s,\"kernel_required\":%s,\"policy\":\"SCHED_FIFO\","
           "\"priority\":%d,\"cpu\":%d,\"memory_locked\":true,"
           "\"cpu_dma_latency_active\":%s,\"spin_us\":%d,"
           "\"cycles\":%" PRIu64 ",\"completed_cycles\":%" PRIu64 ","
           "\"skipped_releases\":%" PRIu64 ",\"deadline_misses\":%" PRIu64 ","
           "\"wake_latency_mean_ns\":%.3Lf,"
           "\"execution_max_ns\":%" PRIu64 ",\"execution_mean_ns\":%.3Lf,"
           "\"execution_scope\":\"base_rate_loop_including_xcp\","
           "\"cycle_interval_samples\":%" PRIu64 ","
           "\"cycle_interval_min_ns\":%" PRIu64 ",\"cycle_interval_max_ns\":%" PRIu64 ","
           "\"cycle_interval_mean_ns\":%.3Lf,"
           "\"cycle_interval_scope\":\"base_rate_loop_start_to_start\","
           "\"measurement_clock\":\"CLOCK_MONOTONIC\","
           "\"model_step_calls\":%" PRIu64 ",\"model_step_completed_calls\":%" PRIu64 ","
           "\"model_step_interval_samples\":%" PRIu64 ","
           "\"model_step_interval_min_ns\":%" PRIu64 ",\"model_step_interval_max_ns\":%" PRIu64 ","
           "\"model_step_interval_mean_ns\":%.3Lf,"
           "\"model_step_execution_min_ns\":%" PRIu64 ",\"model_step_execution_max_ns\":%" PRIu64 ","
           "\"model_step_execution_mean_ns\":%.3Lf,"
           "\"model_step_scope\":\"generated_model_step_including_generated_daq_upload\","
           "\"model_step_interval_scope\":\"generated_model_step_entry_to_entry\","
           "\"final_cycle_includes_termination\":%s,\"elapsed_ns\":%" PRId64 ","
           "\"stop_signal\":%d",
           period_ns, realtime_kernel ? "true" : "false", kernel_required ? "true" : "false",
           configured_priority, configured_cpu, latency_descriptor >= 0 ? "true" : "false", spin_us,
           cycles, completed_cycles,
           skipped_releases, deadline_misses,
           cycles ? wake_total_ns / cycles : 0.0L, execution_max_ns,
           completed_cycles ? execution_total_ns / completed_cycles : 0.0L,
           cycle_interval_samples, cycle_interval_min_ns, cycle_interval_max_ns,
           cycle_interval_samples ? cycle_interval_total_ns / cycle_interval_samples : 0.0L,
           model_step_calls, model_step_completed_calls, model_step_interval_samples,
           model_step_interval_min_ns, model_step_interval_max_ns,
           model_step_interval_samples ? model_step_interval_total_ns / model_step_interval_samples : 0.0L,
           model_step_execution_min_ns, model_step_execution_max_ns,
           model_step_completed_calls ? model_step_execution_total_ns / model_step_completed_calls : 0.0L,
           final_includes_termination ? "true" : "false",
           cycles ? last_finished_ns - first_release_ns : 0, (int)stop_signal);
    write_timing_diagnostics(stdout, &timing);
    fputs("}\n", stdout);
    fflush(stdout);
}

static void signal_stop(int number)
{
    stop_signal = number;
}

static void stop_from_model_thread(void)
{
    finish_step(now_ns());
    exitFcn((int)stop_signal);
    terminateTask(NULL);
    pthread_exit(NULL);
}

static void model_cleanup(void *unused)
{
    (void)unused;
    finish_step(now_ns());
    in_model_thread = 0;
}

static void *model_entry(void *unused)
{
    (void)unused;
    in_model_thread = 1;
    next_release_ns = now_ns() + period_ns;
    pthread_cleanup_push(model_cleanup, NULL);
    baseRateTask(NULL);
    pthread_cleanup_pop(1);
    return NULL;
}

int __wrap_sem_wait(sem_t *semaphore)
{
    int status;
    int64_t current, sleep_deadline_ns;
    struct timespec deadline;
    if (semaphore != &baserateTaskSem || !initialized) {
        do {
            status = __real_sem_wait(semaphore);
        } while (status == -1 && errno == EINTR);
        if (semaphore == &stopSem && initialized && status == 0) {
            require_zero(pthread_join(baseRateThread, NULL), "pthread_join model");
            finish_status_thread();
            report();
            release_latency_request();
        }
        return status;
    }
    if (!in_model_thread) {
        fail("base-rate semaphore used by an unsupported thread", EINVAL);
    }
    current = now_ns();
    finish_step(current);
    if (stop_signal) {
        stop_from_model_thread();
    }
    next_release_ns = simrt_rt_next_future_release(next_release_ns, current, period_ns, &skipped_releases);
    if (next_release_ns < 0) {
        fail("absolute release overflow", EOVERFLOW);
    }
    sleep_deadline_ns = simrt_rt_sleep_deadline_ns(next_release_ns, spin_us);
    current = now_ns();
    if (stop_signal) stop_from_model_thread();
    timing.sleep_performed = current < sleep_deadline_ns;
    timing.sleep_return_lateness_current_ns = 0;
    if (timing.sleep_performed) {
        deadline.tv_sec = (time_t)(sleep_deadline_ns / INT64_C(1000000000));
        deadline.tv_nsec = (long)(sleep_deadline_ns % INT64_C(1000000000));
        do {
            timing.sleep_calls = saturating_add(timing.sleep_calls, 1);
            status = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL);
            if (stop_signal) {
                stop_from_model_thread();
            }
            current = now_ns();
        } while (status == EINTR && current < sleep_deadline_ns);
        require_zero(status == EINTR ? 0 : status, "clock_nanosleep");
        timing.sleep_return_lateness_current_ns = current > sleep_deadline_ns
            ? (uint64_t)(current - sleep_deadline_ns) : 0;
        if (timing.sleep_return_lateness_current_ns > timing.sleep_return_lateness_max_ns) {
            timing.sleep_return_lateness_max_ns = timing.sleep_return_lateness_current_ns;
        }
        if (current > next_release_ns) {
            timing.sleep_return_after_release_count = saturating_add(timing.sleep_return_after_release_count, 1);
        }
    } else {
        timing.sleep_skipped_count = saturating_add(timing.sleep_skipped_count, 1);
    }
    /* Optional bounded busy tail preserves the absolute release grid. */
    while (current < next_release_ns) {
        if (stop_signal) stop_from_model_thread();
#if defined(__i386__) || defined(__x86_64__)
        __asm__ __volatile__("pause");
#endif
        current = now_ns();
    }
    if (stop_signal) stop_from_model_thread();
    release_ns = next_release_ns;
    next_release_ns += period_ns;
    if (cycles == 0) {
        first_release_ns = release_ns;
    } else {
        /* These are actual model-loop starts, including skipped-release gaps. */
        uint64_t interval = (uint64_t)(current - started_ns);
        if (cycle_interval_samples == 0 || interval < cycle_interval_min_ns) {
            cycle_interval_min_ns = interval;
        }
        if (interval > cycle_interval_max_ns) {
            cycle_interval_max_ns = interval;
        }
        cycle_interval_samples = saturating_add(cycle_interval_samples, 1);
        cycle_interval_total_ns += (long double)interval;
    }
    started_ns = current;
    cycles = saturating_add(cycles, 1);
    {
        uint64_t latency = current > release_ns ? (uint64_t)(current - release_ns) : 0;
        wake_total_ns += (long double)latency;
        timing.wake_latency_current_ns = latency;
        if (latency > timing.wake_latency_max_ns) {
            timing.wake_latency_max_ns = latency;
        }
    }
    step_active = 1;
    return 0;
}

int __wrap_sem_post(sem_t *semaphore)
{
    if (initialized && semaphore == &stopSem && in_model_thread) {
        if (step_active) {
            final_includes_termination = 1;
        }
        finish_step(now_ns());
    }
    if (initialized && semaphore == &baserateTaskSem) {
        fail("base-rate semaphore posting is unsupported by absolute scheduling", EINVAL);
    }
    return __real_sem_post(semaphore);
}

void myRTOSInit(double baseRatePeriod, int numSubrates)
{
    pthread_attr_t attr;
    struct sched_param priority;
    struct sigaction action;
    cpu_set_t selected;
    int index;
    int signals[] = {SIGTERM, SIGINT, SIGHUP, SIGQUIT};
    long page_size;
    void *stack;
    if (initialized || numSubrates != 0) {
        fail("runtime requires exactly one model task", EINVAL);
    }
    period_ns = simrt_rt_period_ns(baseRatePeriod);
    if (period_ns < 0) {
        fail("runtime requires a 1 ms, 10 ms, or 100 ms model base period", EINVAL);
    }
    kernel_required = environment_integer("SIMRT_RT_REQUIRE_KERNEL", 1, 0, 1);
    realtime_kernel = is_realtime_kernel();
    if (kernel_required && !realtime_kernel) {
        fail("PREEMPT_RT kernel required (/sys/kernel/realtime != 1)", ENOTSUP);
    }
    configured_priority = environment_integer("SIMRT_RT_PRIORITY", 40, 1, 49);
    simrt_rt_prepare();
    spin_us = environment_integer("SIMRT_RT_SPIN_US", 500, 0, 500);
    if (environment_integer("SIMRT_RT_LOW_LATENCY", 1, 0, 1)) request_low_latency();
    CPU_ZERO(&selected);
    CPU_SET(configured_cpu, &selected);
    page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) {
        fail("page size", EINVAL);
    }
    stack = mmap(NULL, THREAD_STACK_BYTES + (size_t)page_size, PROT_READ | PROT_WRITE,
                 MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (stack == MAP_FAILED) {
        fail("mmap model stack", errno);
    }
    /* Touch every model stack page before locking and before entering SCHED_FIFO. */
    memset(stack, 0, THREAD_STACK_BYTES + (size_t)page_size);
    if (mprotect(stack, (size_t)page_size, PROT_NONE) != 0) {
        fail("model stack guard", errno);
    }
    if (mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
        fail("mlockall: grant sufficient locked-memory limit/CAP_IPC_LOCK", errno);
    }
    if (sem_init(&baserateTaskSem, 0, 0) != 0 || sem_init(&stopSem, 0, 0) != 0) {
        fail("sem_init", errno);
    }
    memset(&action, 0, sizeof(action));
    action.sa_handler = signal_stop;
    sigemptyset(&action.sa_mask);
    for (index = 0; index < (int)(sizeof(signals) / sizeof(signals[0])); ++index) {
        if (sigaction(signals[index], &action, NULL) != 0) {
            fail("sigaction", errno);
        }
    }
    require_zero(pthread_attr_init(&attr), "pthread_attr_init");
    require_zero(pthread_attr_setstack(&attr, (char *)stack + page_size, THREAD_STACK_BYTES), "pthread_attr_setstack");
    require_zero(pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED), "pthread_attr_setinheritsched");
    require_zero(pthread_attr_setschedpolicy(&attr, SCHED_FIFO), "pthread_attr_setschedpolicy");
    memset(&priority, 0, sizeof(priority));
    priority.sched_priority = configured_priority;
    require_zero(pthread_attr_setschedparam(&attr, &priority), "pthread_attr_setschedparam");
    require_zero(pthread_attr_setaffinity_np(&attr, sizeof(selected), &selected), "pthread_attr_setaffinity_np");
    initialized = 1;
    start_status_thread();
    require_zero(pthread_create(&baseRateThread, &attr, model_entry, NULL),
                 "pthread_create SCHED_FIFO: grant rtprio/CAP_SYS_NICE and sufficient locked-memory limit");
    require_zero(pthread_attr_destroy(&attr), "pthread_attr_destroy");
}
