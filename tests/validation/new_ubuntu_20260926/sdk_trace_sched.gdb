set pagination off
set debuginfod enabled off
set breakpoint pending on
set $sched_calls = 0
break pthread_setschedparam
commands
silent
printf "SDK_SCHED thread=%lu policy=%d priority=%d\n", $rdi, $rsi, *(int *)$rdx
set $sched_calls = $sched_calls + 1
continue
end
run
printf "SDK_SCHED_COUNT=%d\n", $sched_calls
