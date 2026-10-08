#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
#include "simrt_serial.h"
#include "serial_loopback_protocol.h"
#include <errno.h>
#include <fcntl.h>
#include <linux/serial.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

typedef struct {
    const char *device;
    int fd, have_termios, have_rs485, touched;
    struct termios original;
    struct serial_rs485 rs485;
    uint32_t token;
} saved_port;
static saved_port ports[2]={{.fd=-1},{.fd=-1}};
static volatile sig_atomic_t stop_signal;

static void interrupted(int signal_number) { stop_signal=signal_number; }

static uint64_t milliseconds(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC,&value)<0) return 0;
    return (uint64_t)value.tv_sec*1000+(uint64_t)value.tv_nsec/1000000;
}

static int active(uint64_t deadline)
{
    if (stop_signal) return -EINTR;
    if (milliseconds()>=deadline) return -ETIMEDOUT;
    return 0;
}

static int parse_number(const char *text, unsigned minimum, unsigned maximum, unsigned *result)
{
    char *end;
    unsigned long value;
    errno=0;
    if (!text[0] || text[0]=='-' || text[0]=='+') return -1;
    value=strtoul(text,&end,10);
    if (errno || *end || value<minimum || value>maximum) return -1;
    *result=(unsigned)value;
    return 0;
}

static int snapshot(saved_port *port, const char *device)
{
    struct stat identity;
    int exclusive=0;
    port->device=device;
    if (strncmp(device,"/dev/",5) || strlen(device)>=256) return -EINVAL;
    port->fd=open(device,O_RDWR|O_NOCTTY|O_NONBLOCK|O_CLOEXEC);
    if (port->fd<0) return -errno;
    if (fstat(port->fd,&identity)<0) return -errno;
    if (!S_ISCHR(identity.st_mode)) return -ENOTTY;
#ifdef TIOCGEXCL
    if (ioctl(port->fd,TIOCGEXCL,&exclusive)<0 && errno!=ENOTTY && errno!=EINVAL) return -errno;
    if (exclusive) return -EBUSY;
#else
    (void)exclusive;
#endif
    if (tcgetattr(port->fd,&port->original)<0) return -errno;
    port->have_termios=1;
    memset(&port->rs485,0,sizeof(port->rs485));
    if (ioctl(port->fd,TIOCGRS485,&port->rs485)==0) port->have_rs485=1;
    else if (errno!=ENOTTY && errno!=EINVAL && errno!=EOPNOTSUPP) return -errno;
    return 0;
}

static int same_termios(const struct termios *a, const struct termios *b)
{
    return a->c_iflag==b->c_iflag && a->c_oflag==b->c_oflag &&
        a->c_cflag==b->c_cflag && a->c_lflag==b->c_lflag &&
        a->c_line==b->c_line && !memcmp(a->c_cc,b->c_cc,NCCS) &&
        cfgetispeed(a)==cfgetispeed(b) && cfgetospeed(a)==cfgetospeed(b);
}

static int restore_rs485_state(int fd, const struct serial_rs485 *original)
{
    struct serial_rs485 actual, requested;
    memset(&actual,0,sizeof(actual));
    if (ioctl(fd,TIOCGRS485,&actual)<0) return -errno;
    /* Some RS232 UARTs expose a zero RS485 state but reject its setter. */
    if (!memcmp(&actual,original,sizeof(actual))) return 0;
    requested=*original;
    if (ioctl(fd,TIOCSRS485,&requested)<0 || ioctl(fd,TIOCGRS485,&actual)<0) return -errno;
    return memcmp(&actual,original,sizeof(actual)) ? -EIO : 0;
}

static int restore_ports(void)
{
    int i, result=0;
    for (i=1;i>=0;--i) {
        saved_port *port=&ports[i];
        struct termios actual;
        if (port->fd<0) continue;
        if (port->touched && port->have_termios) {
            if (tcflush(port->fd,TCIOFLUSH)<0) {
                fprintf(stderr,"%s: flush during cleanup failed: %s\n",port->device,strerror(errno)); result=-1;
            }
            if (tcsetattr(port->fd,TCSANOW,&port->original)<0 || tcgetattr(port->fd,&actual)<0 ||
                !same_termios(&port->original,&actual)) {
                fprintf(stderr,"%s: original termios restoration/verification failed\n",port->device); result=-1;
            }
            if (port->have_rs485) {
                int status=restore_rs485_state(port->fd,&port->rs485);
                if (status) {
                    fprintf(stderr,"%s: original RS485 restoration/verification failed: %s\n",port->device,strerror(-status)); result=-1;
                }
            }
        }
        simrt_serial_close(port->token);
        port->token=0;
        if (close(port->fd)<0) result=-1;
        port->fd=-1;
    }
    return result;
}

static int nonce_bytes(uint8_t nonce[8])
{
    int fd=open("/dev/urandom",O_RDONLY|O_CLOEXEC), status=0;
    unsigned position=0;
    if (fd<0) return -errno;
    while (position<8) {
        ssize_t count=read(fd,nonce+position,8-position);
        if (count<0 && errno==EINTR && !stop_signal) continue;
        if (count<=0) { status=count<0 ? -errno : -EIO; break; }
        position+=(unsigned)count;
    }
    close(fd);
    return status;
}

static int exchange(unsigned direction, uint32_t sequence, const uint8_t nonce[8],
                    uint64_t deadline, uint32_t *transmitted, uint32_t *received)
{
    uint8_t expected[SERIAL_FRAME_SIZE], actual[SERIAL_FRAME_SIZE], chunk[SERIAL_FRAME_SIZE];
    uint32_t sent=0, used=0, count;
    int status;
    const char *mismatch;
    unsigned source=direction, destination=1-direction;
    serial_make_frame(expected,nonce,sequence,(uint8_t)direction);
    /* Drop only prior test traffic, including local RS485 echo, before the next direction. */
    if (tcflush(ports[0].fd,TCIFLUSH)<0 || tcflush(ports[1].fd,TCIFLUSH)<0) return -errno;
    while (sent<SERIAL_FRAME_SIZE || used<SERIAL_FRAME_SIZE) {
        if ((status=active(deadline))) return status;
        if (sent<SERIAL_FRAME_SIZE) {
            status=simrt_serial_send(ports[source].token,expected+sent,SERIAL_FRAME_SIZE-sent,
                                   SERIAL_FRAME_SIZE-sent,&count);
            if (status && status!=-EAGAIN && status!=-EINTR) return status;
            sent+=count; *transmitted+=count;
        }
        status=simrt_serial_receive(ports[destination].token,chunk,sizeof(chunk),&count);
        if (status && status!=-EAGAIN && status!=-EINTR) return status;
        if (count>SERIAL_FRAME_SIZE-used) {
            fprintf(stderr,"direction %u sequence %u: unexpected extra bytes\n",direction,sequence);
            return -EBADMSG;
        }
        memcpy(actual+used,chunk,count); used+=count; *received+=count;
        if (sent<SERIAL_FRAME_SIZE || used<SERIAL_FRAME_SIZE) usleep(1000);
    }
    mismatch=serial_validate_frame(actual,expected);
    if (mismatch) {
        fprintf(stderr,"direction %u sequence %u: %s mismatch\n",direction,sequence,mismatch);
        return -EBADMSG;
    }
    /* Give half-duplex automatic direction control a bounded turnaround interval. */
    usleep(2000);
    return active(deadline);
}

int main(int argc, char **argv)
{
    unsigned baud=115200, rounds=32, timeout_ms=10000, mode, rts=1, i, sequence, completed=0, frames=0;
    uint8_t nonce[8]={0};
    uint32_t transmitted=0, received=0;
    uint64_t start=milliseconds(), deadline;
    int status=0, restored;
    struct sigaction action;
    struct stat identities[2];
    if (argc<4 || argc>7 ||
        (argc>4 && parse_number(argv[4],1200,921600,&baud)) ||
        (argc>5 && parse_number(argv[5],1,10000,&rounds)) ||
        (argc>6 && parse_number(argv[6],100,120000,&timeout_ms))) {
        fprintf(stderr,"Usage: %s DEVICE_A DEVICE_B MODE [BAUD=115200 [ROUNDS=32 [TIMEOUT_MS=10000]]]\n"
            "MODE: rs232 | rs485-auto | rs485-rts-high | rs485-rts-low\n"
            "Exactly two specified ports, 8N1, alternating directions; timeout covers the entire run.\n",argv[0]);
        return 2;
    }
    if (!strcmp(argv[3],"rs232")) mode=0;
    else if (!strcmp(argv[3],"rs485-auto")) mode=1;
    else if (!strcmp(argv[3],"rs485-rts-high")) mode=2;
    else if (!strcmp(argv[3],"rs485-rts-low")) { mode=2; rts=0; }
    else { fprintf(stderr,"Unsupported mode: %s\n",argv[3]); return 2; }
    memset(&action,0,sizeof(action)); action.sa_handler=interrupted;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT,&action,NULL)<0 || sigaction(SIGTERM,&action,NULL)<0 || sigaction(SIGHUP,&action,NULL)<0) {
        perror("Install cleanup signal handlers"); return 2;
    }
    deadline=start+timeout_ms;
    fprintf(stderr,"Selected ports only: %s <-> %s; mode=%s, %u baud 8N1, %u rounds, %u ms total\n",
            argv[1],argv[2],argv[3],baud,rounds,timeout_ms);
    for (i=0;i<2;++i) {
        status=snapshot(&ports[i],argv[i+1]);
        if (status) { fprintf(stderr,"Snapshot %s failed: %s\n",argv[i+1],strerror(-status)); goto done; }
        if (fstat(ports[i].fd,&identities[i])<0) { status=-errno; goto done; }
    }
    if (identities[0].st_rdev==identities[1].st_rdev) {
        fprintf(stderr,"The two paths refer to the same serial device\n"); status=-EINVAL; goto done;
    }
    if ((status=nonce_bytes(nonce))) goto done;
    for (i=0;i<2;++i) {
        if ((status=active(deadline))) goto done;
        ports[i].touched=1;
        status=simrt_serial_open(ports[i].device,baud,8,0,1,(uint8_t)mode,(uint8_t)rts,0,0,&ports[i].token);
        if (status) { fprintf(stderr,"Configure %s failed: %s\n",ports[i].device,strerror(-status)); goto done; }
    }
    for (sequence=0;sequence<rounds;++sequence) {
        for (i=0;i<2;++i) {
            status=exchange(i,sequence,nonce,deadline,&transmitted,&received);
            if (status) {
                fprintf(stderr,"%s -> %s, sequence %u: %s\n",ports[i].device,ports[1-i].device,sequence,strerror(-status));
                goto done;
            }
            ++frames;
        }
        ++completed;
    }
done:
    restored=restore_ports()==0;
    printf("{\"passed\":%s,\"mode\":\"%s\",\"baud\":%u,\"rounds_completed\":%u,"
        "\"frames_verified\":%u,\"tx_bytes\":%u,\"rx_bytes\":%u,\"status\":%d,"
        "\"restore_ok\":%s,\"signal\":%d,\"elapsed_ms\":%llu,\"nonce\":\"",
        status==0 && restored ? "true":"false",argv[3],baud,completed,frames,transmitted,received,status,
        restored ? "true":"false",(int)stop_signal,(unsigned long long)(milliseconds()-start));
    for (i=0;i<8;++i) printf("%02x",nonce[i]);
    puts("\"}");
    return status || !restored ? 1:0;
}
