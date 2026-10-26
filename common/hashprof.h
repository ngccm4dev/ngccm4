/* Hash-cycle accounting for the hashing app (HASHING_PROFILE builds, obj/hashprof/).
 *
 * Every hash primitive and ICCS hash wrapper in common/ brackets its body with
 * HASHPROF_BEGIN()/HASHPROF_END(). Only the outermost bracket accumulates, so
 * nested calls (sm3hash -> sm3_bit -> sm3_bit_compress -> sm3_bit_compress_asm)
 * are counted once. The hashing ELF is linked with
 * -Wl,--wrap=KeccakF1600_StatePermute -Wl,--wrap=KeccakF1600_StatePermute_plain
 * -Wl,--wrap=sm3_bit_compress_asm, so the
 * assembly primitives are counted whoever calls them (common/hashprof.c).
 * Outside HASHING_PROFILE builds the macros are empty. */
#ifndef HASHPROF_H
#define HASHPROF_H

#ifdef HASHING_PROFILE
#include <stdint.h>
#include "hal.h"
extern unsigned long long hash_cycles; /* defined by the hashing app (crypto_kem/hashing.c and siblings) */
extern unsigned int hashprof_depth;    /* common/hashprof.c */
extern uint64_t hashprof_t0;
#define HASHPROF_BEGIN() \
    do { if (hashprof_depth++ == 0) hashprof_t0 = hal_get_time(); } while (0)
#define HASHPROF_END() \
    do { if (--hashprof_depth == 0) hash_cycles += (unsigned long long)(hal_get_time() - hashprof_t0); } while (0)
#else
#define HASHPROF_BEGIN() do { } while (0)
#define HASHPROF_END() do { } while (0)
#endif

#endif /* HASHPROF_H */
