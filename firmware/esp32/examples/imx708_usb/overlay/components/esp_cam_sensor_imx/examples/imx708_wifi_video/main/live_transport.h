/* SPDX-License-Identifier: Apache-2.0 */
#ifndef LIVE_TRANSPORT_H
#define LIVE_TRANSPORT_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

/* write() must bound its blocking time by remaining_us. A partial write does
 * not renew the frame's deadline. Zero and negative writes end the session. */
typedef int (*live_write_fn)(void *, const uint8_t *, size_t, int64_t remaining_us);
typedef int64_t (*live_clock_fn)(void *);

static inline bool live_send_all(void *ctx, const uint8_t *data, size_t len,
                                 int64_t budget_us, live_write_fn write,
                                 live_clock_fn clock)
{
    const int64_t deadline = clock(ctx) + budget_us;
    size_t sent = 0;
    while (sent < len) {
        int64_t remaining = deadline - clock(ctx);
        if (remaining <= 0) return false;
        int n = write(ctx, data + sent, len - sent, remaining);
        if (n <= 0 || (size_t)n > len - sent) return false;
        sent += (size_t)n;
    }
    return clock(ctx) <= deadline;
}

/* The PTS clock may wrap. Only move forward to a newer IDR; jumping backwards
 * to the previous IDR would repeatedly replay the same GOP on a slow link.
 * If no newer IDR exists, preserve the decoding chain until one arrives. */
static inline bool live_should_resync(uint32_t wanted_pts, uint32_t latest_pts,
                                      uint32_t wanted_seq, uint32_t idr_seq,
                                      uint32_t backlog_ms)
{
    return (uint32_t)(latest_pts - wanted_pts) > backlog_ms && idr_seq > wanted_seq;
}

#endif
