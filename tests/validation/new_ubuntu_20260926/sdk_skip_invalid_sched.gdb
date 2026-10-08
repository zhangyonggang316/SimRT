set pagination off
set debuginfod enabled off
set breakpoint pending on
set $invalid_sched_calls = 0
break pthread_setschedparam if $rdi == 0
commands
silent
printf "SDK_INVALID_SCHED thread=%lu policy=%d priority=%d\n", $rdi, $rsi, *(int *)$rdx
set $invalid_sched_calls = $invalid_sched_calls + 1
return (int)3
continue
end
run
printf "SDK_INVALID_SCHED_COUNT=%d\n", $invalid_sched_calls
