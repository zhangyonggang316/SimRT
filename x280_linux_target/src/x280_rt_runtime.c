/* Opt-in 1/10/100 ms, single-task Linux runtime for the generated R2024b main. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "linuxinitialize.h"
#include "rtwtypes.h"
#include "MW_custom_RTOS_header.h"
#include <inttypes.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>

#if (MT != 0) || (MW_NUMBER_SUBRATES != 0) || (MW_IS_CONCURRENT != 0)
#error "X280 RT requires single-task code generation, including for multirate models"
#endif
#if (MW_NUMBER_APERIODIC_TASKS > 0) || (MW_NUMBER_TIMER_DRIVEN_TASKS > 0)
#error "X280 RT does not support asynchronous or independently scheduled tasks"
#endif
#if defined(MW_SOC_ENABLED) || defined(MW_SCHEDULE_TASK_WITH_ALSA_AUDIO) || defined(MW_NEEDS_BACKGROUND_TASK)
#error "X280 RT does not support auxiliary scheduler/background task configurations"
#endif

#define THREAD_STACK_BYTES (1024U * 1024U)

extern volatile boolean_T runModel;
extern int __real_sem_wait(sem_t *semaphore);
extern int __real_sem_post(sem_t *semaphore);

static volatile sig_atomic_t stop_signal;
static __thread int in_model_thread;
static int initialized;
static int report_written;
static int configured_cpu;
static int configured_priority;
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
static uint64_t wake_max_ns;
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
static long double model_step_interval_total_ns;
static long double model_step_execution_total_ns;

static void fail(const char *operation, int code)
{
    fprintf(stderr, "X280 RT initialization/runtime failure: %s: %s (%d)\n",
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

int64_t x280_rt_period_ns(double period_seconds)
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

void x280_rt_step_begin(void)
{
    int64_t current;
    if (!initialized || !in_model_thread || !step_active || model_step_active) {
        fail("model_step begin outside an active model release", EINVAL);
    }
    current = now_ns();
    if (model_step_calls > 0) {
        uint64_t interval = (uint64_t)(current - model_step_started_ns);
        if (model_step_interval_samples == 0 || interval < model_step_interval_min_ns) {
            model_step_interval_min_ns = interval;
        }
        if (interval > model_step_interval_max_ns) {
            model_step_interval_max_ns = interval;
        }
        model_step_interval_samples = saturating_add(model_step_interval_samples, 1);
        model_step_interval_total_ns += (long double)interval;
    }
    model_step_started_ns = current;
    model_step_calls = saturating_add(model_step_calls, 1);
    model_step_active = 1;
}

void x280_rt_step_end(void)
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
    model_step_completed_calls = saturating_add(model_step_completed_calls, 1);
    model_step_active = 0;
}

/* Advance directly to a future release. Missed periods never become a semaphore backlog. */
int64_t x280_rt_next_future_release(int64_t scheduled, int64_t now, int64_t period,
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
}

static void report(void)
{
    if (report_written) {
        return;
    }
    report_written = 1;
    printf("{\"event\":\"x280_rt_summary\",\"period_ns\":%" PRId64 ","
           "\"realtime_kernel\":%s,\"kernel_required\":%s,\"policy\":\"SCHED_FIFO\","
           "\"priority\":%d,\"cpu\":%d,\"memory_locked\":true,"
           "\"cycles\":%" PRIu64 ",\"completed_cycles\":%" PRIu64 ","
           "\"skipped_releases\":%" PRIu64 ",\"deadline_misses\":%" PRIu64 ","
           "\"wake_latency_max_ns\":%" PRIu64 ",\"wake_latency_mean_ns\":%.3Lf,"
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
           "\"stop_signal\":%d}\n",
           period_ns, realtime_kernel ? "true" : "false", kernel_required ? "true" : "false",
           configured_priority, configured_cpu, cycles, completed_cycles,
           skipped_releases, deadline_misses, wake_max_ns,
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
    int64_t current;
    struct timespec deadline;
    if (semaphore != &baserateTaskSem || !initialized) {
        do {
            status = __real_sem_wait(semaphore);
        } while (status == -1 && errno == EINTR);
        if (semaphore == &stopSem && initialized && status == 0) {
            require_zero(pthread_join(baseRateThread, NULL), "pthread_join model");
            report();
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
    next_release_ns = x280_rt_next_future_release(next_release_ns, current, period_ns, &skipped_releases);
    if (next_release_ns < 0) {
        fail("absolute release overflow", EOVERFLOW);
    }
    deadline.tv_sec = (time_t)(next_release_ns / INT64_C(1000000000));
    deadline.tv_nsec = (long)(next_release_ns % INT64_C(1000000000));
    do {
        status = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL);
        if (stop_signal) {
            stop_from_model_thread();
        }
    } while (status == EINTR);
    require_zero(status, "clock_nanosleep");
    current = now_ns();
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
        if (latency > wake_max_ns) {
            wake_max_ns = latency;
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
    cpu_set_t allowed, selected;
    int index, default_cpu = -1;
    int signals[] = {SIGTERM, SIGINT, SIGHUP, SIGQUIT};
    long page_size;
    void *stack;
    if (initialized || numSubrates != 0) {
        fail("runtime requires exactly one model task", EINVAL);
    }
    period_ns = x280_rt_period_ns(baseRatePeriod);
    if (period_ns < 0) {
        fail("runtime requires a 1 ms, 10 ms, or 100 ms model base period", EINVAL);
    }
    kernel_required = environment_integer("X280_RT_REQUIRE_KERNEL", 1, 0, 1);
    realtime_kernel = is_realtime_kernel();
    if (kernel_required && !realtime_kernel) {
        fail("PREEMPT_RT kernel required (/sys/kernel/realtime != 1)", ENOTSUP);
    }
    configured_priority = environment_integer("X280_RT_PRIORITY", 40, 1, 49);
    CPU_ZERO(&allowed);
    if (sched_getaffinity(0, sizeof(allowed), &allowed) != 0) {
        fail("sched_getaffinity", errno);
    }
    for (index = 0; index < CPU_SETSIZE; ++index) {
        if (CPU_ISSET(index, &allowed)) {
            default_cpu = index;
        }
    }
    configured_cpu = environment_integer("X280_RT_CPU", default_cpu, 0, CPU_SETSIZE - 1);
    if (configured_cpu < 0 || !CPU_ISSET(configured_cpu, &allowed)) {
        fail("X280_RT_CPU is not in the allowed affinity mask", EINVAL);
    }
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
    require_zero(pthread_create(&baseRateThread, &attr, model_entry, NULL),
                 "pthread_create SCHED_FIFO: grant rtprio/CAP_SYS_NICE and sufficient locked-memory limit");
    require_zero(pthread_attr_destroy(&attr), "pthread_attr_destroy");
}
