#ifndef KECCAKF1600_H
#define KECCAKF1600_H

#include <stdint.h>

void KeccakF1600_StateExtractBytes(uint64_t *state, unsigned char *data, unsigned int offset, unsigned int length);
void KeccakF1600_StateXORBytes(uint64_t *state, const unsigned char *data, unsigned int offset, unsigned int length);
void KeccakF1600_StatePermute(uint64_t * state);

/* The assembly keeps the state bit-interleaved; this applies the permutation to a
 * plain little-endian uint64_t[25] state (keccakf1600_plain.c). Scheme code that
 * accesses the lanes directly must call this one. */
void KeccakF1600_StatePermute_plain(uint64_t *state);

#endif