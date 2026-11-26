/* 32-tap Q15 FIR over a 2048-sample block. Build with -DUNROLL4 for the
 * optimised version (four independent accumulators). Prints a checksum. */
#include <stdint.h>
#include <stdio.h>
#define N 2048
#define T 32
static int16_t x[N + T], h[T], y[N];
int main(void) {
    uint32_t s = 12345;
    for (int i = 0; i < N + T; i++) { s = s * 1103515245u + 12345u; x[i] = (int16_t)(s >> 16); }
    for (int k = 0; k < T; k++) h[k] = (int16_t)(1024 - 64 * k);
    for (int n = 0; n < N; n++) {
#ifndef UNROLL4
        int32_t acc = 0;
        for (int k = 0; k < T; k++) acc += (int32_t)x[n + k] * h[k];
#else
        int32_t a0 = 0, a1 = 0, a2 = 0, a3 = 0;
        for (int k = 0; k < T; k += 4) {
            a0 += (int32_t)x[n + k] * h[k];
            a1 += (int32_t)x[n + k + 1] * h[k + 1];
            a2 += (int32_t)x[n + k + 2] * h[k + 2];
            a3 += (int32_t)x[n + k + 3] * h[k + 3];
        }
        int32_t acc = (a0 + a1) + (a2 + a3);
#endif
        acc >>= 15;
        if (acc > 32767) acc = 32767;
        if (acc < -32768) acc = -32768;
        y[n] = (int16_t)acc;
    }
    uint32_t cs = 0;
    for (int n = 0; n < N; n++) cs = cs * 31u + (uint16_t)y[n];
    printf("fir_q15 checksum %08x\n", cs);
    return 0;
}
