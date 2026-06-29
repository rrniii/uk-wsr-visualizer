#include "UKHDF5Reader.h"

#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdocumentation"
#pragma clang diagnostic ignored "-Wdocumentation-deprecated-sync"
#include "hdf5.h"
#pragma clang diagnostic pop

#include <ctype.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void uk_set_error(char *buffer, size_t size, const char *format, ...) {
    if (buffer == NULL || size == 0) {
        return;
    }

    va_list args;
    va_start(args, format);
    vsnprintf(buffer, size, format, args);
    va_end(args);
}

static void uk_copy_cstring(char *destination, size_t size, const char *source) {
    if (destination == NULL || size == 0) {
        return;
    }
    if (source == NULL) {
        destination[0] = '\0';
        return;
    }
    snprintf(destination, size, "%s", source);
}

static int uk_case_equal(const char *left, const char *right) {
    if (left == NULL || right == NULL) {
        return 0;
    }
    while (*left != '\0' && *right != '\0') {
        if (tolower((unsigned char)*left) != tolower((unsigned char)*right)) {
            return 0;
        }
        left++;
        right++;
    }
    return *left == '\0' && *right == '\0';
}

static void uk_normalize_dataset_name(const char *requested, char *out, size_t outSize) {
    if (out == NULL || outSize == 0) {
        return;
    }
    out[0] = '\0';

    if (requested == NULL || requested[0] == '\0') {
        return;
    }

    if (strncmp(requested, "dataset", 7) == 0) {
        snprintf(out, outSize, "%s", requested);
    } else {
        snprintf(out, outSize, "dataset%s", requested);
    }
}

static htri_t uk_path_exists(hid_t file, const char *path) {
    H5E_auto2_t previousFunc = NULL;
    void *previousClientData = NULL;
    H5Eget_auto2(H5E_DEFAULT, &previousFunc, &previousClientData);
    H5Eset_auto2(H5E_DEFAULT, NULL, NULL);
    htri_t exists = H5Lexists(file, path, H5P_DEFAULT);
    H5Eset_auto2(H5E_DEFAULT, previousFunc, previousClientData);
    return exists;
}

static double uk_read_double_attr(hid_t location, const char *name, double fallback) {
    if (H5Aexists(location, name) <= 0) {
        return fallback;
    }

    hid_t attr = H5Aopen(location, name, H5P_DEFAULT);
    if (attr < 0) {
        return fallback;
    }

    double value = fallback;
    if (H5Aread(attr, H5T_NATIVE_DOUBLE, &value) < 0) {
        value = fallback;
    }
    H5Aclose(attr);
    return value;
}

static int uk_read_string_attr(hid_t location, const char *name, char *out, size_t outSize) {
    if (out == NULL || outSize == 0) {
        return 0;
    }
    out[0] = '\0';

    if (H5Aexists(location, name) <= 0) {
        return 0;
    }

    hid_t attr = H5Aopen(location, name, H5P_DEFAULT);
    if (attr < 0) {
        return 0;
    }

    hid_t type = H5Aget_type(attr);
    if (type < 0) {
        H5Aclose(attr);
        return 0;
    }

    int ok = 0;
    if (H5Tget_class(type) == H5T_STRING) {
        if (H5Tis_variable_str(type) > 0) {
            char *value = NULL;
            if (H5Aread(attr, type, &value) >= 0 && value != NULL) {
                uk_copy_cstring(out, outSize, value);
                H5free_memory(value);
                ok = 1;
            }
        } else {
            hsize_t storageSize = H5Aget_storage_size(attr);
            if (storageSize > 0 && storageSize < 4096) {
                char *buffer = (char *)calloc((size_t)storageSize + 1, sizeof(char));
                if (buffer != NULL) {
                    if (H5Aread(attr, type, buffer) >= 0) {
                        buffer[storageSize] = '\0';
                        uk_copy_cstring(out, outSize, buffer);
                        ok = 1;
                    }
                    free(buffer);
                }
            }
        }
    }

    H5Tclose(type);
    H5Aclose(attr);
    return ok;
}

static int uk_find_data_group(
    hid_t file,
    const char *datasetName,
    const char *requestedQuantity,
    char *outDataGroup,
    size_t outDataGroupSize,
    char *outQuantity,
    size_t outQuantitySize
) {
    const int maxGroups = 128;
    char dataGroup[128];
    char whatPath[160];
    char quantity[64];

    for (int index = 1; index <= maxGroups; index++) {
        snprintf(dataGroup, sizeof(dataGroup), "%s/data%d", datasetName, index);
        snprintf(whatPath, sizeof(whatPath), "%s/what", dataGroup);

        if (uk_path_exists(file, whatPath) <= 0) {
            continue;
        }

        hid_t what = H5Gopen2(file, whatPath, H5P_DEFAULT);
        if (what < 0) {
            continue;
        }

        quantity[0] = '\0';
        int hasQuantity = uk_read_string_attr(what, "quantity", quantity, sizeof(quantity));
        H5Gclose(what);

        if (!hasQuantity) {
            continue;
        }

        if (requestedQuantity == NULL || requestedQuantity[0] == '\0' || uk_case_equal(quantity, requestedQuantity)) {
            uk_copy_cstring(outDataGroup, outDataGroupSize, dataGroup);
            uk_copy_cstring(outQuantity, outQuantitySize, quantity);
            return 1;
        }
    }

    return 0;
}

static int uk_find_dataset_and_data_group(
    hid_t file,
    const char *requestedDataset,
    const char *requestedQuantity,
    char *outDatasetName,
    size_t outDatasetNameSize,
    char *outDataGroup,
    size_t outDataGroupSize,
    char *outQuantity,
    size_t outQuantitySize
) {
    char datasetName[64];

    uk_normalize_dataset_name(requestedDataset, datasetName, sizeof(datasetName));
    if (datasetName[0] != '\0') {
        if (uk_path_exists(file, datasetName) <= 0) {
            return 0;
        }
        if (uk_find_data_group(file, datasetName, requestedQuantity, outDataGroup, outDataGroupSize, outQuantity, outQuantitySize)) {
            uk_copy_cstring(outDatasetName, outDatasetNameSize, datasetName);
            return 1;
        }
        return 0;
    }

    for (int index = 1; index <= 128; index++) {
        snprintf(datasetName, sizeof(datasetName), "dataset%d", index);
        if (uk_path_exists(file, datasetName) <= 0) {
            continue;
        }
        if (uk_find_data_group(file, datasetName, requestedQuantity, outDataGroup, outDataGroupSize, outQuantity, outQuantitySize)) {
            uk_copy_cstring(outDatasetName, outDatasetNameSize, datasetName);
            return 1;
        }
    }

    return 0;
}

static int uk_is_missing_value(double raw, double nodata, double undetect) {
    if (isfinite(nodata) && fabs(raw - nodata) < 0.000001) {
        return 1;
    }
    if (isfinite(undetect) && fabs(raw - undetect) < 0.000001) {
        return 1;
    }
    return 0;
}

int UKHDF5ReadODIMField(
    const char *filePath,
    const char *requestedDataset,
    const char *requestedQuantity,
    UKHDF5PolarField *outField,
    char *errorBuffer,
    size_t errorBufferSize
) {
    if (outField == NULL) {
        uk_set_error(errorBuffer, errorBufferSize, "No output field was provided.");
        return 0;
    }

    memset(outField, 0, sizeof(UKHDF5PolarField));
    outField->heightM = NAN;
    outField->elevationDeg = NAN;

    if (filePath == NULL || filePath[0] == '\0') {
        uk_set_error(errorBuffer, errorBufferSize, "No HDF5 file path was provided.");
        return 0;
    }

    H5Eset_auto2(H5E_DEFAULT, NULL, NULL);

    hid_t file = H5Fopen(filePath, H5F_ACC_RDONLY, H5P_DEFAULT);
    if (file < 0) {
        uk_set_error(errorBuffer, errorBufferSize, "Could not open HDF5 file.");
        return 0;
    }

    int ok = 0;
    char datasetName[64];
    char dataGroup[128];
    char dataPath[160];
    char whatPath[160];
    char wherePath[128];
    char quantity[64];
    double *rawValues = NULL;
    float *values = NULL;
    hid_t rootWhere = -1;
    hid_t datasetWhere = -1;
    hid_t what = -1;
    hid_t dataset = -1;
    hid_t dataspace = -1;

    datasetName[0] = '\0';
    dataGroup[0] = '\0';
    quantity[0] = '\0';

    if (!uk_find_dataset_and_data_group(
            file,
            requestedDataset,
            requestedQuantity,
            datasetName,
            sizeof(datasetName),
            dataGroup,
            sizeof(dataGroup),
            quantity,
            sizeof(quantity)
        )) {
        uk_set_error(
            errorBuffer,
            errorBufferSize,
            "Could not find %s in the selected ODIM dataset.",
            requestedQuantity != NULL && requestedQuantity[0] != '\0' ? requestedQuantity : "a readable field"
        );
        goto done;
    }

    snprintf(dataPath, sizeof(dataPath), "%s/data", dataGroup);
    snprintf(whatPath, sizeof(whatPath), "%s/what", dataGroup);
    snprintf(wherePath, sizeof(wherePath), "%s/where", datasetName);

    rootWhere = H5Gopen2(file, "where", H5P_DEFAULT);
    datasetWhere = H5Gopen2(file, wherePath, H5P_DEFAULT);
    what = H5Gopen2(file, whatPath, H5P_DEFAULT);
    dataset = H5Dopen2(file, dataPath, H5P_DEFAULT);

    if (rootWhere < 0 || datasetWhere < 0 || what < 0 || dataset < 0) {
        uk_set_error(errorBuffer, errorBufferSize, "The selected ODIM field is missing required metadata or data.");
        goto done;
    }

    dataspace = H5Dget_space(dataset);
    if (dataspace < 0) {
        uk_set_error(errorBuffer, errorBufferSize, "Could not inspect the selected HDF5 dataset.");
        goto done;
    }

    int rank = H5Sget_simple_extent_ndims(dataspace);
    hsize_t dims[2] = {0, 0};
    if (rank != 2 || H5Sget_simple_extent_dims(dataspace, dims, NULL) < 0) {
        uk_set_error(errorBuffer, errorBufferSize, "The selected HDF5 dataset is not a 2-D polar field.");
        goto done;
    }

    if (dims[0] == 0 || dims[1] == 0 || dims[0] > 4096 || dims[1] > 4096) {
        uk_set_error(errorBuffer, errorBufferSize, "The selected HDF5 dataset has an unsupported shape.");
        goto done;
    }

    int rows = (int)dims[0];
    int columns = (int)dims[1];
    size_t count = (size_t)rows * (size_t)columns;
    rawValues = (double *)malloc(count * sizeof(double));
    values = (float *)malloc(count * sizeof(float));
    if (rawValues == NULL || values == NULL) {
        uk_set_error(errorBuffer, errorBufferSize, "Not enough memory to decode the selected HDF5 field.");
        goto done;
    }

    if (H5Dread(dataset, H5T_NATIVE_DOUBLE, H5S_ALL, H5S_ALL, H5P_DEFAULT, rawValues) < 0) {
        uk_set_error(errorBuffer, errorBufferSize, "Could not read the selected HDF5 dataset.");
        goto done;
    }

    double gain = uk_read_double_attr(what, "gain", 1.0);
    double offset = uk_read_double_attr(what, "offset", 0.0);
    double nodata = uk_read_double_attr(what, "nodata", NAN);
    double undetect = uk_read_double_attr(what, "undetect", NAN);

    for (size_t index = 0; index < count; index++) {
        double raw = rawValues[index];
        if (!isfinite(raw) || uk_is_missing_value(raw, nodata, undetect)) {
            values[index] = NAN;
        } else {
            values[index] = (float)(raw * gain + offset);
        }
    }

    outField->values = values;
    outField->rows = rows;
    outField->columns = columns;
    outField->valueCount = (int)count;
    outField->latitude = uk_read_double_attr(rootWhere, "lat", NAN);
    outField->longitude = uk_read_double_attr(rootWhere, "lon", NAN);
    outField->heightM = uk_read_double_attr(rootWhere, "height", NAN);
    outField->elevationDeg = uk_read_double_attr(datasetWhere, "elangle", NAN);
    outField->rstartKm = uk_read_double_attr(datasetWhere, "rstart", 0.0);
    outField->rscaleM = uk_read_double_attr(datasetWhere, "rscale", 1000.0);
    outField->columns = (int)uk_read_double_attr(datasetWhere, "nbins", (double)columns);
    outField->rows = (int)uk_read_double_attr(datasetWhere, "nrays", (double)rows);
    if (outField->rows != rows || outField->columns != columns) {
        outField->rows = rows;
        outField->columns = columns;
    }
    uk_copy_cstring(outField->datasetName, sizeof(outField->datasetName), datasetName);
    uk_copy_cstring(outField->quantity, sizeof(outField->quantity), quantity[0] == '\0' ? requestedQuantity : quantity);

    values = NULL;
    ok = 1;

done:
    if (dataspace >= 0) {
        H5Sclose(dataspace);
    }
    if (dataset >= 0) {
        H5Dclose(dataset);
    }
    if (what >= 0) {
        H5Gclose(what);
    }
    if (datasetWhere >= 0) {
        H5Gclose(datasetWhere);
    }
    if (rootWhere >= 0) {
        H5Gclose(rootWhere);
    }
    if (file >= 0) {
        H5Fclose(file);
    }
    free(rawValues);
    free(values);
    return ok;
}

int UKHDF5InspectODIMFields(
    const char *filePath,
    UKHDF5FieldRecord *records,
    int capacity,
    int *outCount,
    char *errorBuffer,
    size_t errorBufferSize
) {
    if (outCount != NULL) {
        *outCount = 0;
    }
    if (records == NULL || capacity <= 0) {
        uk_set_error(errorBuffer, errorBufferSize, "No output field metadata buffer was provided.");
        return 0;
    }
    if (filePath == NULL || filePath[0] == '\0') {
        uk_set_error(errorBuffer, errorBufferSize, "No HDF5 file path was provided.");
        return 0;
    }

    H5Eset_auto2(H5E_DEFAULT, NULL, NULL);

    hid_t file = H5Fopen(filePath, H5F_ACC_RDONLY, H5P_DEFAULT);
    if (file < 0) {
        uk_set_error(errorBuffer, errorBufferSize, "Could not open HDF5 file.");
        return 0;
    }

    int count = 0;
    char datasetName[64];
    char wherePath[128];
    char dataGroup[128];
    char whatPath[160];
    char dataPath[160];
    char quantity[64];

    for (int datasetIndex = 1; datasetIndex <= 128 && count < capacity; datasetIndex++) {
        snprintf(datasetName, sizeof(datasetName), "dataset%d", datasetIndex);
        if (uk_path_exists(file, datasetName) <= 0) {
            continue;
        }

        snprintf(wherePath, sizeof(wherePath), "%s/where", datasetName);
        hid_t datasetWhere = H5Gopen2(file, wherePath, H5P_DEFAULT);
        double elevationDeg = datasetWhere >= 0 ? uk_read_double_attr(datasetWhere, "elangle", NAN) : NAN;
        if (datasetWhere >= 0) {
            H5Gclose(datasetWhere);
        }

        for (int dataIndex = 1; dataIndex <= 128 && count < capacity; dataIndex++) {
            snprintf(dataGroup, sizeof(dataGroup), "%s/data%d", datasetName, dataIndex);
            snprintf(whatPath, sizeof(whatPath), "%s/what", dataGroup);
            snprintf(dataPath, sizeof(dataPath), "%s/data", dataGroup);
            if (uk_path_exists(file, whatPath) <= 0 || uk_path_exists(file, dataPath) <= 0) {
                continue;
            }

            hid_t what = H5Gopen2(file, whatPath, H5P_DEFAULT);
            if (what < 0) {
                continue;
            }

            quantity[0] = '\0';
            int hasQuantity = uk_read_string_attr(what, "quantity", quantity, sizeof(quantity));
            H5Gclose(what);
            if (!hasQuantity || quantity[0] == '\0') {
                continue;
            }

            int rows = 0;
            int columns = 0;
            hid_t dataset = H5Dopen2(file, dataPath, H5P_DEFAULT);
            if (dataset >= 0) {
                hid_t dataspace = H5Dget_space(dataset);
                if (dataspace >= 0) {
                    hsize_t dims[2] = {0, 0};
                    int rank = H5Sget_simple_extent_ndims(dataspace);
                    if (rank == 2 && H5Sget_simple_extent_dims(dataspace, dims, NULL) >= 0) {
                        rows = (int)dims[0];
                        columns = (int)dims[1];
                    }
                    H5Sclose(dataspace);
                }
                H5Dclose(dataset);
            }

            memset(&records[count], 0, sizeof(UKHDF5FieldRecord));
            uk_copy_cstring(records[count].datasetName, sizeof(records[count].datasetName), datasetName);
            records[count].dataIndex = dataIndex;
            uk_copy_cstring(records[count].quantity, sizeof(records[count].quantity), quantity);
            records[count].rows = rows;
            records[count].columns = columns;
            records[count].elevationDeg = elevationDeg;
            count++;
        }
    }

    H5Fclose(file);
    if (outCount != NULL) {
        *outCount = count;
    }
    if (count == 0) {
        uk_set_error(errorBuffer, errorBufferSize, "No ODIM data fields were found in the HDF5 file.");
    }
    return count > 0;
}

void UKHDF5FreePolarField(UKHDF5PolarField *field) {
    if (field == NULL) {
        return;
    }
    free(field->values);
    field->values = NULL;
    field->rows = 0;
    field->columns = 0;
    field->valueCount = 0;
}
