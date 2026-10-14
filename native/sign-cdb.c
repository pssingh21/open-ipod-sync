#include <glib.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "rijndael.h"

#define OFF_DB_ID   0x18
#define LEN_DB_ID   8
#define OFF_HASH58  0x58
#define LEN_HASH58  20
#define OFF_HASH72  0x72
#define LEN_HASH72  46
#define CDB_HEADER_LEN 244

/* Hash72 algorithm key used by this legacy Apple database format. */
static const uint8_t AES_KEY[16] = {
    0x61,0x8c,0xa1,0x0d,0xc7,0xf5,0x7f,0xd3,
    0xb4,0x72,0x3e,0x08,0x15,0x74,0x63,0xd7
};

struct HashInfo {
    uint8_t header[6];
    uint8_t uuid[20];
    uint8_t rndpart[12];
    uint8_t iv[16];
} __attribute__((packed));

static void compute_cdb_sha1(const uint8_t *src, size_t len, uint8_t out[20])
{
    if (len < OFF_HASH72 + LEN_HASH72) {
        fprintf(stderr, "file too small\n");
        exit(1);
    }
    uint8_t *tmp = g_malloc(len);
    memcpy(tmp, src, len);
    memset(tmp + OFF_DB_ID, 0, LEN_DB_ID);
    memset(tmp + OFF_HASH58, 0, LEN_HASH58);
    memset(tmp + OFF_HASH72, 0, LEN_HASH72);

    GChecksum *cs = g_checksum_new(G_CHECKSUM_SHA1);
    g_checksum_update(cs, tmp, len);
    gsize outlen = 20;
    g_checksum_get_digest(cs, out, &outlen);
    g_checksum_free(cs);
    g_free(tmp);
    if (outlen != 20) {
        fprintf(stderr, "unexpected SHA1 length\n");
        exit(1);
    }
}

static void hash_generate(uint8_t signature[46], const uint8_t sha1[20],
                          const uint8_t iv[16], const uint8_t rnd[12])
{
    uint8_t plaintext[32] = {0};
    uint8_t output[32] = {0};
    memcpy(plaintext, sha1, 20);
    memcpy(plaintext + 20, rnd, 12);
    signature[0] = 0x01;
    signature[1] = 0x00;
    memcpy(signature + 2, rnd, 12);
    aes_set_key((uint8_t *)AES_KEY);
    aes_encrypt(iv, plaintext, output, 32);
    memcpy(signature + 14, output, 32);
}

static int hash_extract(const uint8_t signature[46], const uint8_t sha1[20],
                        uint8_t iv[16], uint8_t rnd[12])
{
    uint8_t plaintext[32] = {0};
    uint8_t output[32] = {0};
    if (signature[0] != 0x01 || signature[1] != 0x00)
        return -1;
    memcpy(plaintext, sha1, 20);
    memcpy(plaintext + 20, signature + 2, 12);
    memcpy(output, plaintext, 32);
    aes_set_key((uint8_t *)AES_KEY);
    aes_decrypt(plaintext, (uint8_t *)signature + 14, output, 16);
    if (memcmp(plaintext + 16, output + 16, 16) != 0)
        return -1;
    memcpy(iv, output, 16);
    memcpy(rnd, signature + 2, 12);
    return 0;
}

static int read_file(const char *path, gchar **buf, gsize *len)
{
    GError *error = NULL;
    if (!g_file_get_contents(path, buf, len, &error)) {
        fprintf(stderr, "read failed for %s: %s\n", path,
                error ? error->message : "unknown error");
        if (error) g_error_free(error);
        return 0;
    }
    return 1;
}

static int valid_cdb(const gchar *buf, gsize len)
{
    return len >= CDB_HEADER_LEN && memcmp(buf, "mhbd", 4) == 0;
}

int main(int argc, char **argv)
{
    if (argc != 5) {
        fprintf(stderr,
                "usage: %s <live-signed-cdb> <HashInfo> <unsigned-cdb> <output>\n",
                argv[0]);
        return 2;
    }
    const char *live_path = argv[1];
    const char *hashinfo_path = argv[2];
    const char *unsigned_path = argv[3];
    const char *output_path = argv[4];

    struct stat st;
    if (stat(output_path, &st) == 0) {
        fprintf(stderr, "refusing to overwrite existing output: %s\n", output_path);
        return 1;
    }

    gchar *live = NULL, *unsigned_data = NULL, *hibuf = NULL;
    gsize live_len = 0, unsigned_len = 0, hilen = 0;
    if (!read_file(live_path, &live, &live_len) ||
        !read_file(unsigned_path, &unsigned_data, &unsigned_len) ||
        !read_file(hashinfo_path, &hibuf, &hilen)) {
        g_free(live); g_free(unsigned_data); g_free(hibuf);
        return 1;
    }

    if (!valid_cdb(live, live_len) || !valid_cdb(unsigned_data, unsigned_len)) {
        fprintf(stderr, "invalid mhbd CDB container\n");
        return 1;
    }
    if (hilen != sizeof(struct HashInfo)) {
        fprintf(stderr, "HashInfo length is %zu, expected %zu\n",
                (size_t)hilen, sizeof(struct HashInfo));
        return 1;
    }
    struct HashInfo hi;
    memcpy(&hi, hibuf, sizeof(hi));
    if (memcmp(hi.header, "HASHv0", 6) != 0) {
        fprintf(stderr, "bad HashInfo header\n");
        return 1;
    }

    /* Calibrate only against the current device's own Apple-signed CDB. */
    uint8_t live_sha1[20], regenerated_live[46];
    compute_cdb_sha1((uint8_t *)live, live_len, live_sha1);
    hash_generate(regenerated_live, live_sha1, hi.iv, hi.rndpart);
    if (memcmp(live + OFF_HASH72, regenerated_live, LEN_HASH72) != 0) {
        fprintf(stderr, "ABORT: pristine calibration failed\n");
        return 1;
    }

    uint8_t recovered_iv[16], recovered_rnd[12];
    if (hash_extract((uint8_t *)live + OFF_HASH72, live_sha1,
                     recovered_iv, recovered_rnd) != 0 ||
        memcmp(recovered_iv, hi.iv, sizeof(recovered_iv)) != 0 ||
        memcmp(recovered_rnd, hi.rndpart, sizeof(recovered_rnd)) != 0) {
        fprintf(stderr, "ABORT: live inverse Hash72 verification failed\n");
        return 1;
    }

    for (size_t i = 0; i < LEN_HASH72; i++) {
        if ((uint8_t)unsigned_data[OFF_HASH72 + i] != 0) {
            fprintf(stderr, "unsigned CDB Hash72 is not zero\n");
            return 1;
        }
    }

    uint8_t candidate_sha1[20], candidate_sig[46];
    compute_cdb_sha1((uint8_t *)unsigned_data, unsigned_len, candidate_sha1);
    hash_generate(candidate_sig, candidate_sha1, hi.iv, hi.rndpart);

    if (hash_extract(candidate_sig, candidate_sha1,
                     recovered_iv, recovered_rnd) != 0 ||
        memcmp(recovered_iv, hi.iv, sizeof(recovered_iv)) != 0 ||
        memcmp(recovered_rnd, hi.rndpart, sizeof(recovered_rnd)) != 0) {
        fprintf(stderr, "ABORT: inverse Hash72 verification failed\n");
        return 1;
    }

    uint8_t *signed_data = g_malloc(unsigned_len);
    memcpy(signed_data, unsigned_data, unsigned_len);
    memcpy(signed_data + OFF_HASH72, candidate_sig, LEN_HASH72);

    size_t outside_changes = 0;
    for (size_t i = 0; i < unsigned_len; i++) {
        if ((uint8_t)unsigned_data[i] != signed_data[i] &&
            !(i >= OFF_HASH72 && i < OFF_HASH72 + LEN_HASH72))
            outside_changes++;
    }
    if (outside_changes != 0) {
        fprintf(stderr, "ABORT: bytes outside Hash72 changed\n");
        return 1;
    }
    if (memcmp(unsigned_data + CDB_HEADER_LEN,
               signed_data + CDB_HEADER_LEN,
               unsigned_len - CDB_HEADER_LEN) != 0) {
        fprintf(stderr, "ABORT: compressed body changed\n");
        return 1;
    }

    uint8_t final_sha1[20], final_regenerated[46];
    compute_cdb_sha1(signed_data, unsigned_len, final_sha1);
    if (memcmp(final_sha1, candidate_sha1, 20) != 0) {
        fprintf(stderr, "ABORT: final SHA1 changed unexpectedly\n");
        return 1;
    }
    hash_generate(final_regenerated, final_sha1, hi.iv, hi.rndpart);
    if (memcmp(signed_data + OFF_HASH72, final_regenerated, LEN_HASH72) != 0) {
        fprintf(stderr, "ABORT: final signature verification failed\n");
        return 1;
    }

    GError *error = NULL;
    if (!g_file_set_contents(output_path, (gchar *)signed_data,
                             unsigned_len, &error)) {
        fprintf(stderr, "write output failed: %s\n",
                error ? error->message : "unknown error");
        if (error) g_error_free(error);
        return 1;
    }

    printf("pristine calibration: PASS\n");
    printf("inverse Hash72 verification: PASS\n");
    printf("bytes outside Hash72 changed: 0\n");
    printf("compressed body changed: 0\n");
    printf("final signature verification: PASS\n");

    g_free(signed_data);
    g_free(live); g_free(unsigned_data); g_free(hibuf);
    return 0;
}
