set pagination off
set debuginfod enabled off
set breakpoint pending on
break pthread_key_create
commands
silent
printf "THREAD_KEY destructor=%p\n", $rsi
info symbol $rsi
continue
end
break release_sdk
commands
silent
printf "SDK_RELEASE_BEGIN\n"
info sharedlibrary
continue
end
run
thread apply all bt
