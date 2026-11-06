#ifndef UKHDF5Reader_h
#define UKHDF5Reader_h

#include <stddef.h>
#include <stdint.h>

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
    /* 0 measured, 1 NODATA, 2 UNDETECT, 3 nonfinite; source is never edited. */
    uint8_t *sourceStates;
    double *startAzimuthDeg;
    double *stopAzimuthDeg;
    int measuredAzimuths;
    double beamWidthDeg;
} UKHDF5PolarField;

typedef struct {
    char datasetName[64];
    int dataIndex;
    char quantity[64];
    int rows;
    int columns;
    double elevationDeg;
} UKHDF5FieldRecord;

int UKHDF5ReadODIMField(
    const char *filePath,
    const char *requestedDataset,
    const char *requestedQuantity,
    UKHDF5PolarField *outField,
    char *errorBuffer,
    size_t errorBufferSize
);

int UKHDF5InspectODIMFields(
    const char *filePath,
    UKHDF5FieldRecord *records,
    int capacity,
    int *outCount,
    char *errorBuffer,
    size_t errorBufferSize
);

void UKHDF5FreePolarField(UKHDF5PolarField *field);

#ifdef __cplusplus
}
#endif

#endif
