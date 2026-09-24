#define _POSIX_C_SOURCE 200809L
#include <signal.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t running = 1;

static void stop(int signal_number)
{
    (void)signal_number;
    running = 0;
}

int main(void)
{
    struct sigaction action = {0};
    unsigned long tick = 0;
    action.sa_handler = stop;
    sigemptyset(&action.sa_mask);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);
    setvbuf(stdout, NULL, _IOLBF, 0);
    printf("pyXCP SSH deployment demo started, pid=%ld\n", (long)getpid());
    while (running) {
        struct timespec delay = {1, 0};
        printf("tick=%lu\n", tick++);
        nanosleep(&delay, NULL);
    }
    puts("pyXCP SSH deployment demo stopped cleanly");
    return 0;
}
