#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

#include <libimobiledevice/libimobiledevice.h>
#include <libimobiledevice/notification_proxy.h>
#include <libimobiledevice/afc.h>

#define NP_SYNC_WILL_START "com.apple.itunes-mobdev.syncWillStart"
#define NP_SYNC_LOCK_REQUEST "com.apple.itunes-mobdev.syncLockRequest"
#define NP_SYNC_DID_START "com.apple.itunes-mobdev.syncDidStart"
#define NP_SYNC_DID_FINISH "com.apple.itunes-mobdev.syncDidFinish"

static int post(np_client_t np, const char *name)
{
    np_error_t err = np_post_notification(np, name);
    printf("post %-45s : %s (%d)\n", name,
           err == NP_E_SUCCESS ? "PASS" : "FAIL", err);
    fflush(stdout);
    return err == NP_E_SUCCESS ? 0 : -1;
}

int main(void)
{
    idevice_t device = NULL;
    np_client_t np = NULL;
    afc_client_t afc = NULL;
    uint64_t lockfile = 0;
    int locked = 0;
    int result = EXIT_FAILURE;
    idevice_error_t ierr;
    np_error_t nerr;
    afc_error_t aerr;

    /* The Python front-end already requires exactly one connected device. */
    ierr = idevice_new(&device, NULL);
    if (ierr != IDEVICE_E_SUCCESS || !device) {
        fprintf(stderr, "ERROR: idevice_new failed: %d\n", ierr);
        goto cleanup;
    }

    nerr = np_client_start_service(device, &np, "ipod-sync");
    if (nerr != NP_E_SUCCESS || !np) {
        fprintf(stderr, "ERROR: notification proxy failed: %d\n", nerr);
        goto cleanup;
    }

    aerr = afc_client_start_service(device, &afc, "ipod-sync");
    if (aerr != AFC_E_SUCCESS || !afc) {
        fprintf(stderr, "ERROR: AFC service failed: %d\n", aerr);
        goto cleanup;
    }

    if (post(np, NP_SYNC_WILL_START) < 0)
        goto cleanup;

    aerr = afc_file_open(afc, "/com.apple.itunes.lock_sync", AFC_FOPEN_RW, &lockfile);
    if (aerr != AFC_E_SUCCESS || !lockfile) {
        fprintf(stderr, "ERROR: open sync lock failed: %d\n", aerr);
        goto cleanup;
    }

    if (post(np, NP_SYNC_LOCK_REQUEST) < 0)
        goto cleanup;

    for (int i = 0; i < 50; i++) {
        aerr = afc_file_lock(afc, lockfile, AFC_LOCK_EX);
        if (aerr == AFC_E_SUCCESS) {
            locked = 1;
            break;
        }
        if (aerr == AFC_E_OP_WOULD_BLOCK) {
            usleep(200000);
            continue;
        }
        fprintf(stderr, "ERROR: AFC lock failed: %d\n", aerr);
        goto cleanup;
    }
    if (!locked) {
        fprintf(stderr, "ERROR: timed out acquiring sync lock\n");
        goto cleanup;
    }

    if (post(np, NP_SYNC_DID_START) < 0)
        goto cleanup;

    puts("READY");
    fflush(stdout);

    char command[64] = {0};
    if (!fgets(command, sizeof(command), stdin)) {
        puts("Parent pipe closed; finishing sync envelope safely.");
        result = EXIT_FAILURE;
        goto cleanup;
    }

    command[strcspn(command, "\r\n")] = '\0';
    if (strcmp(command, "FINISH") == 0) {
        result = EXIT_SUCCESS;
    } else {
        puts("Envelope received abort/unknown command; closing safely.");
        result = EXIT_FAILURE;
    }

cleanup:
    if (locked && afc && lockfile) {
        aerr = afc_file_lock(afc, lockfile, AFC_LOCK_UN);
        printf("unlock AFC sync lock: %s (%d)\n",
               aerr == AFC_E_SUCCESS ? "PASS" : "FAIL", aerr);
        if (aerr != AFC_E_SUCCESS)
            result = EXIT_FAILURE;
        locked = 0;
    }

    if (afc && lockfile) {
        aerr = afc_file_close(afc, lockfile);
        printf("close sync lock: %s (%d)\n",
               aerr == AFC_E_SUCCESS ? "PASS" : "FAIL", aerr);
        if (aerr != AFC_E_SUCCESS)
            result = EXIT_FAILURE;
        lockfile = 0;
    }

    if (np) {
        nerr = np_post_notification(np, NP_SYNC_DID_FINISH);
        printf("post %-45s : %s (%d)\n", NP_SYNC_DID_FINISH,
               nerr == NP_E_SUCCESS ? "PASS" : "FAIL", nerr);
        if (nerr != NP_E_SUCCESS)
            result = EXIT_FAILURE;
    }

    if (afc) afc_client_free(afc);
    if (np) np_client_free(np);
    if (device) idevice_free(device);
    return result;
}
