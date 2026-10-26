/* Keccak-f[1600] on a plain little-endian uint64_t[25] state, using the assembly
 * permutation of keccakf1600.S. That implementation keeps the state bit-interleaved
 * (each 64-bit lane split into its even and odd bits, see toBitInterleaving in the
 * .S file) and only KeccakF1600_StateXORBytes / StateExtractBytes understand the
 * plain byte view, so a scheme that reads or writes the lanes directly (every
 * reference fips202.c) must go through this wrapper: the plain state is XORed into
 * a zero interleaved state (which interleaves it), permuted, and extracted back.
 * The conversion costs a few hundred cycles per call against roughly ten thousand
 * for the permutation itself. */
#include <stdint.h>
#include <string.h>

#include "keccakf1600.h"

void KeccakF1600_StatePermute_plain(uint64_t *state)
{
    uint64_t interleaved[25];

    memset(interleaved, 0, sizeof(interleaved));
    KeccakF1600_StateXORBytes(interleaved, (const unsigned char *)state, 0, 200);
    KeccakF1600_StatePermute(interleaved);
    KeccakF1600_StateExtractBytes(interleaved, (unsigned char *)state, 0, 200);
}
