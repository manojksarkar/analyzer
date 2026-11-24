#include "Devices.h"

// Names the class: reaches Device::read only, never NorDevice::read.
int NandDevice::read(int lba) {
    return Device::read(lba) + 1;
}
