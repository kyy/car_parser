// brute.c — hex-версия, собирает ВСЕ коллизии
// Компиляция (MSYS2 UCRT64):
//   gcc -O3 -march=native -pthread brute.c -o brute.exe -lcrypto
// Запуск:
//   NTHREADS=8 ./brute.exe 8

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <pthread.h>
#include <time.h>
#include <openssl/hmac.h>
#include <openssl/sha.h>

#define ALPHABET "0123456789ABCDEF"
#define ALPHA_LEN 16

static const uint8_t TARGET[4] = {0xA1, 0x64, 0x8F, 0xCC};

static unsigned char KEY_MACHINE[SHA256_DIGEST_LENGTH];
static unsigned char KEY_PIN[SHA256_DIGEST_LENGTH];

static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;
static volatile uint64_t g_counter = 0;
static volatile int g_done_threads = 0;

// ---------- хранилище результатов ----------
typedef struct {
    char id[64];
    char mc[16];
    char pin[16];
} result_t;

static result_t *g_results = NULL;
static size_t g_results_n = 0;
static size_t g_results_cap = 0;

static void push_result(const char *id, const char *mc, const char *pin) {
    if (g_results_n == g_results_cap) {
        size_t newcap = g_results_cap ? g_results_cap * 2 : 64;
        result_t *tmp = realloc(g_results, newcap * sizeof(result_t));
        if (!tmp) { perror("realloc"); exit(1); }
        g_results = tmp;
        g_results_cap = newcap;
    }
    strncpy(g_results[g_results_n].id,  id,  sizeof(g_results[0].id)  - 1);
    strncpy(g_results[g_results_n].mc,  mc,  sizeof(g_results[0].mc)  - 1);
    strncpy(g_results[g_results_n].pin, pin, sizeof(g_results[0].pin) - 1);
    g_results[g_results_n].id[sizeof(g_results[0].id) - 1] = 0;
    g_results[g_results_n].mc[sizeof(g_results[0].mc) - 1] = 0;
    g_results[g_results_n].pin[sizeof(g_results[0].pin) - 1] = 0;
    g_results_n++;
}

// ---------- derive_key ----------
static void derive_key(const char *mode, unsigned char out[SHA256_DIGEST_LENGTH]) {
    char buf[128];
    snprintf(buf, sizeof(buf), "courage+/v1/%s:3f1c-uzmaster-9a7d", mode);
    SHA256((const unsigned char *)buf, strlen(buf), out);
}

// ---------- normalize ----------
static size_t normalize(const char *in, char *out) {
    size_t j = 0;
    for (size_t i = 0; in[i]; i++) {
        char c = in[i];
        if (c >= 'a' && c <= 'z') c -= 32;
        if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9')) out[j++] = c;
    }
    out[j] = 0;
    return j;
}

// ---------- проверка ----------
static int check_candidate(const char *cand, size_t len,
                           char *out_mc, char *out_pin) {
    unsigned char mac[SHA256_DIGEST_LENGTH];
    unsigned int mac_len = 0;
    HMAC(EVP_sha256(), KEY_MACHINE, SHA256_DIGEST_LENGTH,
         (const unsigned char *)cand, len, mac, &mac_len);

    if (mac[0] != TARGET[0] || mac[1] != TARGET[1] ||
        mac[2] != TARGET[2] || mac[3] != TARGET[3]) return 0;

    sprintf(out_mc, "%02X%02X-%02X%02X", mac[0], mac[1], mac[2], mac[3]);

    unsigned char pmac[SHA256_DIGEST_LENGTH];
    unsigned int pmac_len = 0;
    HMAC(EVP_sha256(), KEY_PIN, SHA256_DIGEST_LENGTH,
         (const unsigned char *)cand, len, pmac, &pmac_len);

    uint32_t n = (((uint32_t)(pmac[0] & 0x7F)) << 24)
               | ((uint32_t)pmac[1] << 16)
               | ((uint32_t)pmac[2] << 8)
               |  (uint32_t)pmac[3];
    sprintf(out_pin, "%06u", n % 1000000u);
    return 1;
}

// ---------- worker ----------
typedef struct {
    int length;
    int prefix_len;
    char prefix[64];
    int thread_id;
    int nthreads;
} worker_arg_t;

static void *worker(void *argp) {
    worker_arg_t *a = (worker_arg_t *)argp;
    int tail = a->length - a->prefix_len;
    if (tail < 0) return NULL;

    char cand[64];
    memcpy(cand, a->prefix, a->prefix_len);
    cand[a->length] = 0;

    int idx[64];
    memset(idx, 0, sizeof(idx));

    uint64_t start = (uint64_t)a->thread_id;
    for (int p = tail - 1; p >= 0; p--) {
        idx[p] = (int)(start % ALPHA_LEN);
        start /= ALPHA_LEN;
    }

    uint64_t step = (uint64_t)a->nthreads;
    uint64_t local = 0;
    const uint64_t report_every = 200000;

    while (1) {
        for (int p = 0; p < tail; p++)
            cand[a->prefix_len + p] = ALPHABET[idx[p]];

        char mc[16], pin[16];
        if (check_candidate(cand, a->length, mc, pin)) {
            pthread_mutex_lock(&g_lock);
            push_result(cand, mc, pin);
            pthread_mutex_unlock(&g_lock);
        }

        local++;
        if (local >= report_every) {
            pthread_mutex_lock(&g_lock);
            g_counter += local;
            pthread_mutex_unlock(&g_lock);
            local = 0;
        }

        // +step в mixed-radix
        uint64_t add = step;
        for (int p = tail - 1; p >= 0 && add > 0; p--) {
            uint64_t cur = (uint64_t)idx[p] + add;
            idx[p] = (int)(cur % ALPHA_LEN);
            add = cur / ALPHA_LEN;
        }
        if (add > 0) break; // диапазон исчерпан
    }

    pthread_mutex_lock(&g_lock);
    g_counter += local;
    g_done_threads++;
    pthread_mutex_unlock(&g_lock);
    return NULL;
}

static double now_sec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s <length> [prefix]\n", argv[0]);
        return 1;
    }
    int length = atoi(argv[1]);
    const char *prefix_in = argc > 2 ? argv[2] : "";

    char prefix[64];
    size_t plen = normalize(prefix_in, prefix);
    if ((int)plen > length) {
        fprintf(stderr, "prefix longer than length\n");
        return 1;
    }

    derive_key("machine", KEY_MACHINE);
    derive_key("pin", KEY_PIN);

    int nthreads = 8;
    const char *env = getenv("NTHREADS");
    if (env) nthreads = atoi(env);
    if (nthreads < 1) nthreads = 1;

    // total = ALPHA_LEN^tail
    uint64_t total = 1;
    for (int i = 0; i < length - (int)plen; i++) total *= ALPHA_LEN;

    printf("[*] hex length=%d prefix='%s' threads=%d total=%llu\n",
           length, prefix, nthreads, (unsigned long long)total);

    pthread_t *th = calloc(nthreads, sizeof(pthread_t));
    worker_arg_t *args = calloc(nthreads, sizeof(worker_arg_t));

    double t0 = now_sec();

    for (int i = 0; i < nthreads; i++) {
        args[i].length = length;
        args[i].prefix_len = (int)plen;
        memcpy(args[i].prefix, prefix, plen);
        args[i].prefix[plen] = 0;
        args[i].thread_id = i;
        args[i].nthreads = nthreads;
        pthread_create(&th[i], NULL, worker, &args[i]);
    }

    uint64_t last = 0;
    double last_t = t0;
    while (g_done_threads < nthreads) {
        struct timespec ts = {0, 500 * 1000000};
        nanosleep(&ts, NULL);
        uint64_t cur = g_counter;
        double t = now_sec();
        double rate = (cur - last) / (t - last_t);
        double pct = total ? 100.0 * (double)cur / (double)total : 0.0;
        fprintf(stderr, "\r[.] %llu / %llu (%.3f%%)  %.0f H/s  found=%zu   ",
                (unsigned long long)cur, (unsigned long long)total,
                pct, rate, g_results_n);
        fflush(stderr);
        last = cur;
        last_t = t;
    }

    for (int i = 0; i < nthreads; i++) pthread_join(th[i], NULL);

    double t1 = now_sec();
    fprintf(stderr, "\n");

    printf("\n=== RESULTS: %zu matches ===\n", g_results_n);
    for (size_t i = 0; i < g_results_n; i++) {
        printf("%s  ->  %s  PIN=%s\n",
               g_results[i].id, g_results[i].mc, g_results[i].pin);
    }
    printf("[*] elapsed %.2f s, checked ~%llu\n",
           t1 - t0, (unsigned long long)g_counter);

    free(g_results);
    free(th);
    free(args);
    return g_results_n ? 0 : 2;
}