#include "Devices.h"

int NorDevice::read(int lba) {
    return lba * 2;
}
