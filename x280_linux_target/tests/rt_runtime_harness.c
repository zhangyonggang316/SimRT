/* Linux-only runtime harness. Build against the generated bundle headers. */
#include "linuxinitialize.h"
#include "rtwtypes.h"
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

volatile boolean_T runModel = 1;
sem_t stopSem;
sem_t baserateTaskSem;
pthread_t baseRateThread;
pthread_t schedulerThread;
static unsigned completed;
static unsigned cycle_limit = 200;
static double period_seconds = 0.001;
static int normal_load;

extern int64_t x280_rt_next_future_release(int64_t, int64_t, int64_t, uint64_t *);
extern int64_t x280_rt_period_ns(double);
extern void x280_rt_step_begin(void);
extern void x280_rt_step_end(void);

static int64_t monotonic_ns(void)
{
    struct timespec now;
    assert(clock_gettime(CLOCK_MONOTONIC, &now) == 0);
    return (int64_t)now.tv_sec * INT64_C(1000000000) + now.tv_nsec;
}

void exitFcn(int number)
{
    (void)number;
    runModel = 0;
}

void *terminateTask(void *unused)
{
    (void)unused;
    runModel = 0;
    assert(sem_post(&stopSem) == 0);
    return NULL;
}

void *baseRateTask(void *unused)
{
    (void)unused;
    while (runModel && completed < cycle_limit) {
        int64_t end;
        assert(sem_wait(&baserateTaskSem) == 0);
        ++completed;
        x280_rt_step_begin();
        end = monotonic_ns() + (!normal_load && completed % 20 == 0
                              ? x280_rt_period_ns(period_seconds) * 5 / 2 : 100000);
        while (monotonic_ns() < end) {
        }
        x280_rt_step_end();
    }
    terminateTask(NULL);
    pthread_exit(NULL);
}

static void math_tests(void)
{
    uint64_t skipped = 0;
    assert(x280_rt_next_future_release(1000, 900, 100, &skipped) == 1000 && skipped == 0);
    assert(x280_rt_next_future_release(1000, 1000, 100, &skipped) == 1100 && skipped == 1);
    assert(x280_rt_next_future_release(1100, 1450, 100, &skipped) == 1500 && skipped == 5);
    assert(x280_rt_next_future_release(1500, 99999999, 100, &skipped) == 100000000);
    assert(x280_rt_next_future_release(10, 20, 0, &skipped) == -1);
    assert(x280_rt_next_future_release(INT64_MAX - 10, INT64_MAX - 1, 100, &skipped) == -1);
    skipped = UINT64_MAX - 1;
    assert(x280_rt_next_future_release(100, 500, 100, &skipped) == 600 && skipped == UINT64_MAX);
    assert(x280_rt_period_ns(0.001) == 1000000);
    assert(x280_rt_period_ns(0.01) == 10000000);
    assert(x280_rt_period_ns(0.1) == 100000000);
    assert(x280_rt_period_ns(0.0) == -1);
    assert(x280_rt_period_ns(-0.001) == -1);
    assert(x280_rt_period_ns(0.005) == -1);
    assert(x280_rt_period_ns(0.0010000000001) == -1);
    assert(x280_rt_period_ns(NAN) == -1);
    assert(x280_rt_period_ns(INFINITY) == -1);
    puts("{\"event\":\"x280_rt_math_tests\",\"passed\":16}");
}

static int usage(const char *program)
{
    fprintf(stderr, "Usage: %s [--period-ms 1|10|100] [--normal-load] "
                    "[--cycles N | --long] [--math | --bad-period | --bad-subrates]\n", program);
    return 2;
}

int main(int argc, char **argv)
{
    int index;
    int run_math = 0, bad_period = 0, bad_subrates = 0;
    for (index = 1; index < argc; ++index) {
        if (strcmp(argv[index], "--math") == 0) {
            run_math = 1;
        } else if (strcmp(argv[index], "--bad-period") == 0) {
            bad_period = 1;
        } else if (strcmp(argv[index], "--bad-subrates") == 0) {
            bad_subrates = 1;
        } else if (strcmp(argv[index], "--normal-load") == 0) {
            normal_load = 1;
        } else if (strcmp(argv[index], "--long") == 0) {
            cycle_limit = 60000;
        } else if (strcmp(argv[index], "--period-ms") == 0) {
            if (++index == argc) {
                return usage(argv[0]);
            }
            if (strcmp(argv[index], "1") == 0) {
                period_seconds = 0.001;
            } else if (strcmp(argv[index], "10") == 0) {
                period_seconds = 0.01;
            } else if (strcmp(argv[index], "100") == 0) {
                period_seconds = 0.1;
            } else {
                return usage(argv[0]);
            }
        } else if (strcmp(argv[index], "--cycles") == 0) {
            char *end;
            unsigned long value;
            if (++index == argc || argv[index][0] < '0' || argv[index][0] > '9') {
                return usage(argv[0]);
            }
            errno = 0;
            value = strtoul(argv[index], &end, 10);
            if (errno != 0 || *end != '\0' || value == 0 || value > UINT_MAX) {
                return usage(argv[0]);
            }
            cycle_limit = (unsigned)value;
        } else {
            return usage(argv[0]);
        }
    }
    if (run_math) {
        math_tests();
        return 0;
    }
    if (bad_period) {
        myRTOSInit(0.005, 0);
        return 99;
    }
    if (bad_subrates) {
        myRTOSInit(period_seconds, 1);
        return 99;
    }
    myRTOSInit(period_seconds, 0);
    assert(sem_wait(&stopSem) == 0);
    return 0;
}
