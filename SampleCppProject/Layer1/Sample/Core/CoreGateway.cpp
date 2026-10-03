#include "CoreGateway.h"
#include "CoreStats.h"

PUBLIC int gatewayRecordSample(int total, int sample) {
    return statsAccumulate(total, sample);           // CoreGateway -> CoreStats
}

PUBLIC int gatewayMean(int total, int count, int lastSample) {
    int withLast = statsAccumulate(total, lastSample);   // CoreGateway -> CoreStats
    return statsAverage(withLast, count + 1);            // CoreGateway -> CoreStats
}
