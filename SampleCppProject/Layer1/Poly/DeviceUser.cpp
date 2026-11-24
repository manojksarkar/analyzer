#include "Devices.h"

// Through a Device*: any of the three.
int devReadAny(Device* d, int lba) {
    return d->read(lba);
}

// Through a NandDevice&: NandDevice::read only.
int devReadNand(NandDevice& n, int lba) {
    return n.read(lba);
}
