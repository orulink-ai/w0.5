/* SPDX-License-Identifier: Apache-2.0 */
#include "live_transport.h"
#include "../../components/imx_wifi/include/board_audio_buffer.h"

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

    /* Startup waits for actual PCM samples, not time since AUDIO START. */
    static board_audio_buffer_t audio;
    board_audio_packet_t out;
    static int16_t pcm[480] = {1234};
    CHECK(!board_audio_buffer_push(&audio, pcm, 0));
    CHECK(!board_audio_buffer_push(&audio, pcm, 481));
    for (int i = 0; i < 9; i++) CHECK(board_audio_buffer_push(&audio, pcm, 480));
    CHECK(!board_audio_buffer_pop(&audio, &out));
    CHECK(board_audio_buffer_push(&audio, pcm, 479));
    CHECK(!board_audio_buffer_pop(&audio, &out));  /* 4799 samples is still short. */
    CHECK(board_audio_buffer_push(&audio, pcm, 1));
    CHECK(board_audio_buffer_pop(&audio, &out));
    CHECK(out.samples == 480 && out.pcm[0] == 1234 && audio.samples == 4320);

    /* STOP invalidates already popped packets and drops all pending speech. */
    uint32_t old_generation = out.generation;
    board_audio_buffer_reset(&audio);
    CHECK(out.generation != audio.generation && audio.generation != old_generation);
    CHECK(audio.count == 0 && !audio.ending && !audio.playing);
    CHECK(!board_audio_buffer_pop(&audio, &out));

    /* END starts a short utterance, then reports empty only after final pop. */
    CHECK(board_audio_buffer_push(&audio, pcm, 12));
    CHECK(!board_audio_buffer_pop(&audio, &out));
    audio.ending = true;
    CHECK(!board_audio_buffer_drained(&audio));
    CHECK(!board_audio_buffer_push(&audio, pcm, 12));
    CHECK(board_audio_buffer_pop(&audio, &out) && out.samples == 12);
    CHECK(board_audio_buffer_drained(&audio));

    /* Full small-packet queues must start; producer never deadlocks waiting
     * for 200 ms when 20 tiny packets have exhausted bounded slot capacity. */
    board_audio_buffer_reset(&audio);
    for (int i = 0; i < BOARD_AUDIO_QUEUE_PACKETS; i++) {
        pcm[0] = (int16_t)i;
        CHECK(board_audio_buffer_push(&audio, pcm, 1));
    }
    CHECK(!board_audio_buffer_push(&audio, pcm, 1));
    for (int i = 0; i < BOARD_AUDIO_QUEUE_PACKETS; i++) {
        CHECK(board_audio_buffer_pop(&audio, &out));
        CHECK(out.pcm[0] == i && out.samples == 1);
    }
    CHECK(!board_audio_buffer_pop(&audio, &out));
    /* Ring wraps without reordering or retaining stale samples. */
    CHECK(board_audio_buffer_push(&audio, pcm, 480));
    CHECK(board_audio_buffer_pop(&audio, &out) && out.samples == 480);
    audio.ending = true;
    CHECK(board_audio_buffer_drained(&audio));
    return 0;
}

int main(void) { return run_tests(); }
