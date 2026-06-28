#ifndef UKHDF5Reader_h
#define UKHDF5Reader_h

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float *values;
    int rows;
    int columns;
    int valueCount;
    double latitude;
    double longitude;
    double heightM;
    double elevationDeg;
    double rstartKm;
    double rscaleM;
    char datasetName[64];
    char quantity[64];
} UKHDF5PolarField;

int UKHDF5ReadODIMField(
    const char *filePath,
    const char *requestedDataset,
    const char *requestedQuantity,
    UKHDF5PolarField *outField,
    char *errorBuffer,
    size_t errorBufferSize
);

void UKHDF5FreePolarField(UKHDF5PolarField *field);

#ifdef __cplusplus
}
#endif

#endif
