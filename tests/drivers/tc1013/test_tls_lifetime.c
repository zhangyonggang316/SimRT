#define _GNU_SOURCE
#include "../../../toolchain/simrt_linux_target/drivers/tc1013/src/simrt_tc1013_can.h"
#include <assert.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static void *lifecycle(void *directory)
{
    uint32_t token = 0;
    assert(simrt_can_configure_channel(directory, "", 1, 0, 500, 500, 1, &token) == 0);
    assert(token != 0);
    simrt_can_release(token);
    return NULL;
}

int main(int argc, char **argv)
{
    unsigned int index, count;
    unsigned int (*destructors)(void);
    char path[4096];
    void *library, *symbol;
    assert(argc == 2);
    for (index = 0; index < 8; ++index) {
        pthread_t thread;
        assert(pthread_create(&thread, NULL, lifecycle, argv[1]) == 0);
        assert(pthread_join(thread, NULL) == 0);
    }
    assert(snprintf(path, sizeof(path), "%s/libTSCANApiOnLinux.so", argv[1]) > 0);
    library = dlopen(path, RTLD_NOW | RTLD_NOLOAD);
    assert(library != NULL);
    symbol = dlsym(library, "tc1013_test_destructors");
    assert(symbol != NULL && sizeof(symbol) == sizeof(destructors));
    memcpy(&destructors, &symbol, sizeof(destructors));
    count = destructors();
    assert(count == 8);
    assert(dlclose(library) == 0);
    printf("SDK lifecycle completed: 8 thread destructors after channel release\n");
    return 0;
}
