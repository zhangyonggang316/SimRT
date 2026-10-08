#ifndef SIMRT_TEST_DLFCN_H
#define SIMRT_TEST_DLFCN_H
#define RTLD_NOW 2
#define RTLD_GLOBAL 256
#define RTLD_LOCAL 0
#define RTLD_NODELETE 4096
void *dlopen(const char *path, int mode);
void *dlsym(void *library, const char *name);
char *dlerror(void);
int dlclose(void *library);
#endif
