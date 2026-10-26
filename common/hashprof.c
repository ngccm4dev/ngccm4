/* Hash-cycle accounting state and the --wrap trampolines for the assembly hash
 * primitives (see hashprof.h). Compiled into every library; empty outside
 * HASHING_PROFILE builds. mk/scheme.mk links this object into the hashing ELF
 * explicitly so the __wrap_ symbols exist even when nothing else pulls it in. */
#include "hashprof.h"

#ifdef HASHING_PROFILE
#include <stdint.h>

unsigned int hashprof_depth = 0;
uint64_t hashprof_t0 = 0;

extern void __real_KeccakF1600_StatePermute(uint64_t *state);
void __wrap_KeccakF1600_StatePermute(uint64_t *state)
{
    HASHPROF_BEGIN();
    __real_KeccakF1600_StatePermute(state);
    HASHPROF_END();
}

extern void __real_KeccakF1600_StatePermute_plain(uint64_t *state);
void __wrap_KeccakF1600_StatePermute_plain(uint64_t *state)
{
    HASHPROF_BEGIN();
    __real_KeccakF1600_StatePermute_plain(state);
    HASHPROF_END();
}

extern void __real_sm3_bit_compress_asm(unsigned int dgst[8], const unsigned char *msg, unsigned long long blocks);
void __wrap_sm3_bit_compress_asm(unsigned int dgst[8], const unsigned char *msg, unsigned long long blocks)
{
    HASHPROF_BEGIN();
    __real_sm3_bit_compress_asm(dgst, msg, blocks);
    HASHPROF_END();
}
#else
typedef int hashprof_translation_unit_not_empty;
#endif
