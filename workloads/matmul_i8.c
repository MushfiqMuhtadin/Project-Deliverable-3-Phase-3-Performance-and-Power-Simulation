/* 128x128 int8 matrix multiply, int32 result. Build with -DTILED for the
 * optimised version (B transposed, j blocked by 32, k unrolled x4). */
#include <stdint.h>
#include <stdio.h>
#define NN 128
#define JB 32
static int8_t A[NN][NN], B[NN][NN], BT[NN][NN];
static int32_t C[NN][NN];
int main(void) {
    uint32_t s = 777;
    for (int i = 0; i < NN; i++)
        for (int j = 0; j < NN; j++) {
            s = s * 1103515245u + 12345u; A[i][j] = (int8_t)(s >> 24);
            s = s * 1103515245u + 12345u; B[i][j] = (int8_t)(s >> 24);
        }
#ifndef TILED
    for (int i = 0; i < NN; i++)
        for (int j = 0; j < NN; j++) {
            int32_t acc = 0;
            for (int k = 0; k < NN; k++) acc += A[i][k] * B[k][j];
            C[i][j] = acc;
        }
#else
    for (int k = 0; k < NN; k++)
        for (int j = 0; j < NN; j++) BT[j][k] = B[k][j];
    for (int jb = 0; jb < NN; jb += JB)
        for (int i = 0; i < NN; i++)
            for (int j = jb; j < jb + JB; j++) {
                int32_t s0 = 0, s1 = 0;
                for (int k = 0; k < NN; k += 4) {
                    s0 += A[i][k] * BT[j][k];
                    s1 += A[i][k + 1] * BT[j][k + 1];
                    s0 += A[i][k + 2] * BT[j][k + 2];
                    s1 += A[i][k + 3] * BT[j][k + 3];
                }
                C[i][j] = s0 + s1;
            }
#endif
    uint32_t cs = 0;
    for (int i = 0; i < NN; i++)
        for (int j = 0; j < NN; j++) cs = cs * 31u + (uint32_t)C[i][j];
    printf("matmul_i8 checksum %08x\n", cs);
    return 0;
}
