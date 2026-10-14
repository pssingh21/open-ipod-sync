#define _GNU_SOURCE

#include <errno.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef SECCOMP_RET_KILL_PROCESS
#define SECCOMP_RET_KILL_PROCESS SECCOMP_RET_KILL
#endif

#define DENY_SYSCALL(nr)                                                   \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (nr), 0, 1),                     \
    BPF_STMT(                                                               \
        BPF_RET | BPF_K,                                                    \
        SECCOMP_RET_ERRNO | (EPERM & SECCOMP_RET_DATA)                    \
    )

static void fail_errno(const char *what)
{
    fprintf(
        stderr,
        "network-deny-exec: %s: %s\n",
        what,
        strerror(errno)
    );
    exit(111);
}

static void reject_socket_stdio(void)
{
    for (int fd = STDIN_FILENO; fd <= STDERR_FILENO; ++fd) {
        int type = 0;
        socklen_t length = sizeof(type);

        errno = 0;

        if (getsockopt(
                fd,
                SOL_SOCKET,
                SO_TYPE,
                &type,
                &length
            ) == 0) {
            fprintf(
                stderr,
                "network-deny-exec: refusing inherited socket on fd %d\n",
                fd
            );
            exit(112);
        }

        if (errno != ENOTSOCK && errno != EBADF) {
            fail_errno("could not classify standard descriptor");
        }
    }
}

static void close_nonstandard_descriptors(void)
{
    DIR *directory = opendir("/proc/self/fd");

    if (directory == NULL) {
        /*
         * Fail closed rather than risk carrying a previously opened network
         * socket across exec.
         */
        fail_errno("could not open /proc/self/fd");
    }

    const int directory_fd = dirfd(directory);

    for (;;) {
        errno = 0;

        struct dirent *entry = readdir(directory);

        if (entry == NULL) {
            if (errno != 0) {
                fail_errno("could not enumerate /proc/self/fd");
            }

            break;
        }

        char *end = NULL;

        errno = 0;

        const long parsed = strtol(
            entry->d_name,
            &end,
            10
        );

        if (
            errno != 0 ||
            end == entry->d_name ||
            *end != '\0'
        ) {
            continue;
        }

        if (
            parsed <= STDERR_FILENO ||
            parsed == directory_fd
        ) {
            continue;
        }

        if (parsed > 0 && parsed <= 0x7fffffffL) {
            /*
             * Descriptors can disappear while /proc/self/fd is enumerated.
             * close(2) failure is therefore not itself an isolation failure.
             */
            (void)close((int)parsed);
        }
    }

    if (closedir(directory) != 0) {
        fail_errno("could not close /proc/self/fd");
    }
}

static void install_network_filter(void)
{
#if !defined(__x86_64__)
#error "network-deny-exec currently supports x86-64 only"
#endif

    struct sock_filter filter[] = {
        /*
         * Never apply an x86-64 syscall-number filter to an unexpected ABI.
         */
        BPF_STMT(
            BPF_LD | BPF_W | BPF_ABS,
            offsetof(struct seccomp_data, arch)
        ),
        BPF_JUMP(
            BPF_JMP | BPF_JEQ | BPF_K,
            AUDIT_ARCH_X86_64,
            1,
            0
        ),
        BPF_STMT(
            BPF_RET | BPF_K,
            SECCOMP_RET_KILL_PROCESS
        ),

        BPF_STMT(
            BPF_LD | BPF_W | BPF_ABS,
            offsetof(struct seccomp_data, nr)
        ),

#ifdef __NR_socket
        DENY_SYSCALL(__NR_socket),
#endif

#ifdef __NR_socketpair
        DENY_SYSCALL(__NR_socketpair),
#endif

#ifdef __NR_connect
        DENY_SYSCALL(__NR_connect),
#endif

#ifdef __NR_bind
        DENY_SYSCALL(__NR_bind),
#endif

#ifdef __NR_listen
        DENY_SYSCALL(__NR_listen),
#endif

#ifdef __NR_accept
        DENY_SYSCALL(__NR_accept),
#endif

#ifdef __NR_accept4
        DENY_SYSCALL(__NR_accept4),
#endif

#ifdef __NR_sendto
        DENY_SYSCALL(__NR_sendto),
#endif

#ifdef __NR_sendmsg
        DENY_SYSCALL(__NR_sendmsg),
#endif

#ifdef __NR_sendmmsg
        DENY_SYSCALL(__NR_sendmmsg),
#endif

#ifdef __NR_recvfrom
        DENY_SYSCALL(__NR_recvfrom),
#endif

#ifdef __NR_recvmsg
        DENY_SYSCALL(__NR_recvmsg),
#endif

#ifdef __NR_recvmmsg
        DENY_SYSCALL(__NR_recvmmsg),
#endif

#ifdef __NR_shutdown
        DENY_SYSCALL(__NR_shutdown),
#endif

#ifdef __NR_getsockname
        DENY_SYSCALL(__NR_getsockname),
#endif

#ifdef __NR_getpeername
        DENY_SYSCALL(__NR_getpeername),
#endif

#ifdef __NR_setsockopt
        DENY_SYSCALL(__NR_setsockopt),
#endif

#ifdef __NR_getsockopt
        DENY_SYSCALL(__NR_getsockopt),
#endif

        BPF_STMT(
            BPF_RET | BPF_K,
            SECCOMP_RET_ALLOW
        ),
    };

    struct sock_fprog program = {
        .len = (unsigned short)(
            sizeof(filter) / sizeof(filter[0])
        ),
        .filter = filter,
    };

    if (prctl(
            PR_SET_NO_NEW_PRIVS,
            1,
            0,
            0,
            0
        ) != 0) {
        fail_errno("PR_SET_NO_NEW_PRIVS failed");
    }

    if (prctl(
            PR_SET_SECCOMP,
            SECCOMP_MODE_FILTER,
            &program
        ) != 0) {
        fail_errno("PR_SET_SECCOMP failed");
    }
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(
            stderr,
            "usage: %s COMMAND [ARG ...]\n",
            argv[0]
        );
        return 2;
    }

    /*
     * Do not permit an already-open socket to bypass the socket-creation
     * filter. Standard descriptors must not be sockets and every other
     * inherited descriptor is closed before seccomp is installed.
     */
    reject_socket_stdio();
    close_nonstandard_descriptors();

    install_network_filter();

    execvp(
        argv[1],
        &argv[1]
    );

    fail_errno("execvp failed");
    return 111;
}
