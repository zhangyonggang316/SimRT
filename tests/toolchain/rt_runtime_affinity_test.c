/* CPU selection uses mocked sysfs and scheduler calls; no host affinity is changed. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "linuxinitialize.h"
#include <assert.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>

static FILE *test_fopen(const char *path, const char *mode);
static char *test_getenv(const char *name);
static int test_sched_getaffinity(pid_t pid, size_t size, cpu_set_t *cpus);
static int test_sched_setaffinity(pid_t pid, size_t size, const cpu_set_t *cpus);
static int test_fprintf(FILE *file, const char *format, ...);
static void test_exit(int code) __attribute__((noreturn));
#define fopen test_fopen
#define getenv test_getenv
#define sched_getaffinity test_sched_getaffinity
#define sched_setaffinity test_sched_setaffinity
#define fprintf test_fprintf
#define exit test_exit
#include "../../toolchain/simrt_linux_target/src/simrt_rt_runtime.c"
#undef fopen
#undef getenv
#undef sched_getaffinity
#undef sched_setaffinity
#undef fprintf
#undef exit

volatile boolean_T runModel = 1;
sem_t stopSem, baserateTaskSem;
pthread_t baseRateThread, schedulerThread;
static cpu_set_t actual_affinity, cgroup_cpus, online_cpus, requested[8];
static unsigned get_calls, set_calls, get_failure, set_failure;
static const char *isolated_text, *online_text, *topology_text, *fixture_text;
static char *explicit_cpu;
static char messages[2048];
static int expecting_failure, failure_code;
static jmp_buf failed;

int __real_sem_wait(sem_t *semaphore) { (void)semaphore; assert(0); return -1; }
int __real_sem_post(sem_t *semaphore) { (void)semaphore; assert(0); return -1; }
void exitFcn(int number) { (void)number; assert(0); }
void *terminateTask(void *unused) { (void)unused; assert(0); return NULL; }
void *baseRateTask(void *unused) { (void)unused; assert(0); return NULL; }

static void mask(cpu_set_t *cpus, uint32_t bits)
{
    unsigned index;
    CPU_ZERO(cpus);
    for (index = 0; index < 32; ++index) {
        if (bits & (UINT32_C(1) << index)) CPU_SET(index, cpus);
    }
}

static void assert_mask(const cpu_set_t *cpus, uint32_t bits)
{
    cpu_set_t expected;
    mask(&expected, bits);
    assert(CPU_EQUAL(cpus, &expected));
}

static FILE *test_fopen(const char *path, const char *mode)
{
    const char *content = NULL;
    FILE *file;
    assert(strcmp(mode, "r") == 0);
    if (strcmp(path, "/sys/devices/system/cpu/isolated") == 0) content = isolated_text;
    else if (strcmp(path, "/sys/devices/system/cpu/online") == 0) content = online_text;
    else if (strstr(path, "/topology/thread_siblings_list") != NULL) content = topology_text;
    else if (strcmp(path, "fixture") == 0) content = fixture_text;
    else assert(0);
    if (content == NULL) {
        errno = ENOENT;
        return NULL;
    }
    file = tmpfile();
    assert(file != NULL && fputs(content, file) >= 0);
    rewind(file);
    return file;
}

static char *test_getenv(const char *name)
{
    assert(strcmp(name, "SIMRT_RT_CPU") == 0);
    return explicit_cpu;
}

static int test_sched_getaffinity(pid_t pid, size_t size, cpu_set_t *cpus)
{
    assert(pid == 0 && size == sizeof(cpu_set_t));
    if (++get_calls == get_failure) {
        errno = EIO;
        return -1;
    }
    *cpus = actual_affinity;
    return 0;
}

static int test_sched_setaffinity(pid_t pid, size_t size, const cpu_set_t *cpus)
{
    cpu_set_t permitted;
    assert(pid == 0 && size == sizeof(cpu_set_t) && set_calls < 8);
    requested[set_calls++] = *cpus;
    if (set_calls == set_failure) {
        errno = EPERM;
        return -1;
    }
    CPU_AND(&permitted, cpus, &cgroup_cpus);
    CPU_AND(&permitted, &permitted, &online_cpus);
    if (CPU_COUNT(&permitted) == 0) {
        errno = EINVAL;
        return -1;
    }
    actual_affinity = permitted;
    return 0;
}

static int test_fprintf(FILE *file, const char *format, ...)
{
    int result;
    va_list arguments;
    va_start(arguments, format);
    if (file == stderr) {
        size_t length = strlen(messages);
        result = vsnprintf(messages + length, sizeof(messages) - length, format, arguments);
    } else {
        result = vfprintf(file, format, arguments);
    }
    va_end(arguments);
    return result;
}

static void test_exit(int code)
{
    assert(expecting_failure);
    failure_code = code;
    longjmp(failed, 1);
}

static void reset(uint32_t inherited, uint32_t permitted)
{
    affinity_prepared = 0;
    configured_cpu = -1;
    mask(&actual_affinity, inherited);
    mask(&cgroup_cpus, permitted);
    mask(&online_cpus, 15);
    get_calls = set_calls = get_failure = set_failure = 0;
    isolated_text = "2-3\n";
    online_text = "0-3\n";
    topology_text = "2-3\n";
    explicit_cpu = NULL;
    messages[0] = '\0';
    expecting_failure = failure_code = 0;
}

static void expect_failure(const char *message)
{
    expecting_failure = 1;
    if (setjmp(failed) == 0) {
        simrt_rt_prepare();
        assert(0);
    }
    expecting_failure = 0;
    assert(failure_code == EXIT_FAILURE && !affinity_prepared);
    assert(strstr(messages, message) != NULL);
}

static void test_default_and_partial_cpuset(void)
{
    reset(3, 15);
    simrt_rt_prepare();
    assert(configured_cpu == 3 && get_calls == 2 && set_calls == 2);
    assert_mask(&requested[0], 15);
    assert_mask(&runtime_allowed, 15);
    assert_mask(&background_cpus, 3);
    assert_mask(&actual_affinity, 3);
    simrt_rt_prepare();
    assert(get_calls == 2 && set_calls == 2);

    reset(3, 7);
    simrt_rt_prepare();
    assert(configured_cpu == 2 && get_calls == 2 && set_calls == 2);
    assert_mask(&requested[0], 15);
    assert_mask(&runtime_allowed, 7);
    assert_mask(&background_cpus, 3);
}

static void test_unavailable_and_offline_isolated(void)
{
    reset(3, 3);
    topology_text = "0-1\n";
    simrt_rt_prepare();
    assert(configured_cpu == 1);
    assert_mask(&runtime_allowed, 3);
    assert_mask(&background_cpus, 1);
    assert(strstr(messages, "no separate physical core") != NULL);

    reset(3, 15);
    online_text = "0-2\n";
    mask(&online_cpus, 7);
    simrt_rt_prepare();
    assert(configured_cpu == 2);
    assert_mask(&requested[0], 7);

    reset(15, 15);
    isolated_text = "2\n";
    simrt_rt_prepare();
    assert(configured_cpu == 2 && get_calls == 1 && set_calls == 1);
    assert_mask(&background_cpus, 3);
}

static void test_explicit_cpu(void)
{
    reset(3, 15);
    explicit_cpu = "3";
    simrt_rt_prepare();
    assert(configured_cpu == 3);
    assert_mask(&requested[0], 11);
    assert_mask(&background_cpus, 3);

    reset(3, 15);
    explicit_cpu = "2";
    simrt_rt_prepare();
    assert(configured_cpu == 2);
    assert_mask(&requested[0], 7);

    reset(3, 7);
    explicit_cpu = "3";
    expect_failure("isolated model CPU is excluded by the cgroup cpuset");
    assert(set_calls == 1 && get_calls == 2);

    reset(15, 15);
    explicit_cpu = "0";
    topology_text = "0-1\n";
    simrt_rt_prepare();
    assert(configured_cpu == 0 && set_calls == 1);
    assert_mask(&background_cpus, 12);

    reset(3, 15);
    explicit_cpu = "3";
    online_text = "0-2\n";
    mask(&online_cpus, 7);
    expect_failure("not in the allowed affinity mask");
    assert(set_calls == 0);
}

static void test_missing_topology_and_empty_selection(void)
{
    reset(3, 15);
    topology_text = NULL;
    simrt_rt_prepare();
    assert(configured_cpu == 3);
    assert_mask(&background_cpus, 7);
    assert(strstr(messages, "cannot read CPU3 SMT topology") != NULL);

    reset(3, 3);
    isolated_text = "\n";
    topology_text = "0-1\n";
    simrt_rt_prepare();
    assert(configured_cpu == 1 && get_calls == 1 && set_calls == 1);

    reset(0, 0);
    isolated_text = NULL;
    expect_failure("no allowed model CPU");
    assert(set_calls == 0);

    reset(3, 15);
    explicit_cpu = "-1";
    expect_failure("SIMRT_RT_CPU");
    assert(set_calls == 0);
}

static void test_scheduler_errors(void)
{
    reset(3, 15);
    get_failure = 1;
    expect_failure("sched_getaffinity");
    reset(3, 15);
    set_failure = 1;
    expect_failure("cannot discover allowed isolated model CPUs");
    reset(3, 15);
    get_failure = 2;
    expect_failure("cannot discover allowed isolated model CPUs");
    reset(3, 15);
    set_failure = 2;
    expect_failure("background sched_setaffinity");
}

static void test_cpu_lists(void)
{
    cpu_set_t parsed;
    const char *invalid[] = {NULL, "", "\n", "0,", "1-", "3-1", "-1", "0,3x", "1024"};
    size_t index;
    fixture_text = "3\n";
    assert(read_cpu_set("fixture", &parsed));
    assert_mask(&parsed, 8);
    fixture_text = "0-1,3";
    assert(read_cpu_set("fixture", &parsed));
    assert_mask(&parsed, 11);
    fixture_text = "2-3\n";
    assert(read_cpu_set("fixture", &parsed));
    assert_mask(&parsed, 12);
    for (index = 0; index < sizeof(invalid) / sizeof(invalid[0]); ++index) {
        fixture_text = invalid[index];
        CPU_SET(3, &parsed);
        assert(!read_cpu_set("fixture", &parsed) && CPU_COUNT(&parsed) == 0);
    }
}

int main(void)
{
    test_default_and_partial_cpuset();
    test_unavailable_and_offline_isolated();
    test_explicit_cpu();
    test_missing_topology_and_empty_selection();
    test_scheduler_errors();
    test_cpu_lists();
    puts("{\"event\":\"simrt_rt_affinity_tests\",\"passed\":6}");
    return 0;
}
