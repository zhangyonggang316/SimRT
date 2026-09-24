CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Werror -std=c11

.PHONY: all clean
all: demo.elf

demo.elf: main.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f -- demo.elf
