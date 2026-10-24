/* SPDX-License-Identifier: Apache-2.0 */
#include "live_transport.h"

typedef struct {
    int64_t now, cost;
    int step, calls, fail_call;
    size_t written;
    uint8_t bytes[32];
    int64_t budgets[32];
} fake_t;

static int64_t clock_us(void *ctx) { return ((fake_t *)ctx)->now; }
static int write_bytes(void *ctx, const uint8_t *p, size_t n, int64_t remaining)
{
    fake_t *f = ctx;
    f->budgets[f->calls++] = remaining;
    f->now += f->cost < remaining ? f->cost : remaining;
    if (f->fail_call == f->calls) return -1;
    if (f->cost >= remaining) return -1;
    if (f->step <= 0) return f->step;
    if (n > (size_t)f->step) n = (size_t)f->step;
    for (size_t i = 0; i < n; ++i) f->bytes[f->written++] = p[i];
    return (int)n;
}

#define CHECK(expr) do { if (!(expr)) return __LINE__; } while (0)
#ifdef _WIN32
__declspec(dllexport)
#endif
int run_tests(void)
{
    const uint8_t payload[] = {0, 0, 0, 1, 0x65, 0xff, 0, 7};
    /* Short writes must preserve every byte, including Annex-B zero bytes. */
    fake_t f = {.step = 3, .cost = 10};
    CHECK(live_send_all(&f, payload, sizeof(payload), 100, write_bytes, clock_us));
    CHECK(f.calls == 3 && f.written == sizeof(payload));
    for (size_t i = 0; i < sizeof(payload); ++i) CHECK(f.bytes[i] == payload[i]);
    CHECK(f.budgets[0] == 100 && f.budgets[1] == 90 && f.budgets[2] == 80);

    /* A trickling peer must not renew the deadline with each byte. */
    f = (fake_t){.step = 1, .cost = 40};
    CHECK(!live_send_all(&f, payload, sizeof(payload), 100, write_bytes, clock_us));
    CHECK(f.calls == 3 && f.now == 100 && f.written == 2);
    f = (fake_t){.step = 8, .cost = 1000};
    CHECK(!live_send_all(&f, payload, sizeof(payload), 100, write_bytes, clock_us));
    CHECK(f.calls == 1 && f.now == 100);

    /* Closure / failure stops immediately; no busy retry on a zero write. */
    f = (fake_t){.step = 0};
    CHECK(!live_send_all(&f, payload, sizeof(payload), 100, write_bytes, clock_us));
    CHECK(f.calls == 1);
    f = (fake_t){.step = 2, .fail_call = 2};
    CHECK(!live_send_all(&f, payload, sizeof(payload), 100, write_bytes, clock_us));
    CHECK(f.calls == 2 && f.written == 2);
    f = (fake_t){.step = 1};
    CHECK(!live_send_all(&f, payload, sizeof(payload), 0, write_bytes, clock_us));
    CHECK(f.calls == 0);

    CHECK(live_should_resync(100, 1600, 10, 20, 1000));
    CHECK(!live_should_resync(100, 1100, 10, 20, 1000));
    CHECK(!live_should_resync(100, 1600, 10, 9, 1000));
    CHECK(!live_should_resync(100, 1600, 10, 10, 1000));
    CHECK(live_should_resync(UINT32_MAX - 500, 700, 10, 20, 1000));
    return 0;
}

int main(void) { return run_tests(); }
