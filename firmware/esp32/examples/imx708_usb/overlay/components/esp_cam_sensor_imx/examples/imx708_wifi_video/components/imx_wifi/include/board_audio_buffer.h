/* SPDX-License-Identifier: Apache-2.0 */
#pragma once
#include <stdbool.h>
#include <stdint.h>

/* The caller serializes access. 400 ms capacity, 200 ms startup at 24 kHz.
 * Short packets can fill all slots early; a full queue must also start so the
 * producer can always make progress. No allocation and no unbounded backlog. */
#define BOARD_AUDIO_PACKET_SAMPLES 480
#define BOARD_AUDIO_QUEUE_PACKETS 20
#define BOARD_AUDIO_PREFILL_SAMPLES 4800
typedef struct {
    uint32_t generation;
    unsigned samples;
    int16_t pcm[BOARD_AUDIO_PACKET_SAMPLES];
} board_audio_packet_t;
typedef struct {
    board_audio_packet_t slots[BOARD_AUDIO_QUEUE_PACKETS];
    unsigned head, count, samples;
    uint32_t generation;
    bool playing, ending;
} board_audio_buffer_t;

static inline void board_audio_buffer_reset(board_audio_buffer_t *q)
{
    q->generation++;
    q->head = q->count = q->samples = 0;
    q->playing = q->ending = false;
}
static inline bool board_audio_buffer_push(board_audio_buffer_t *q, const int16_t *pcm, unsigned samples)
{
    if (!samples || samples > BOARD_AUDIO_PACKET_SAMPLES || q->ending || q->count == BOARD_AUDIO_QUEUE_PACKETS) return false;
    board_audio_packet_t *p = &q->slots[(q->head + q->count) % BOARD_AUDIO_QUEUE_PACKETS];
    p->generation = q->generation;
    p->samples = samples;
    for (unsigned i = 0; i < samples; i++) p->pcm[i] = pcm[i];
    q->count++;
    q->samples += samples;
    return true;
}
static inline bool board_audio_buffer_pop(board_audio_buffer_t *q, board_audio_packet_t *packet)
{
    if (!q->playing && q->count && (q->samples >= BOARD_AUDIO_PREFILL_SAMPLES ||
            q->count == BOARD_AUDIO_QUEUE_PACKETS || q->ending)) q->playing = true;
    if (!q->playing || !q->count) return false;
    const board_audio_packet_t *p = &q->slots[q->head];
    packet->generation = p->generation;
    packet->samples = p->samples;
    for (unsigned i = 0; i < p->samples; i++) packet->pcm[i] = p->pcm[i];
    q->head = (q->head + 1) % BOARD_AUDIO_QUEUE_PACKETS;
    q->count--;
    q->samples -= packet->samples;
    return true;
}
static inline bool board_audio_buffer_drained(const board_audio_buffer_t *q)
{
    return q->ending && !q->count;
}
