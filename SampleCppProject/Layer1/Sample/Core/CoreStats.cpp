#include "CoreStats.h"

// Called only from CoreGateway, another unit of the same component -- the cross-unit
// hop that earns CoreGateway's functions a Dynamic Behaviour row (see CoreStats.h).

PUBLIC int statsAccumulate(int total, int sample) {
    if (sample < 0) {
        return total;                         // a negative sample is ignored
    }
    if (total > STATS_MAX_TOTAL - sample) {
        return STATS_MAX_TOTAL;               // saturate instead of overflowing
    }
    return total + sample;
}

PUBLIC int statsAverage(int total, int count) {
    if (count <= 0) {
        return 0;
    }
    return total / count;
}
