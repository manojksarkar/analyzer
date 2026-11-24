#pragma once

// Test: a virtual call reaches the method it names and the overrides below it (review SWE3-028).
// Each class's read is in a unit of its own, so each caller shows in the interface tables.

class Device {
public:
    virtual ~Device() = default;
    virtual int read(int lba);
};

class NandDevice : public Device {
public:
    int read(int lba) override;
};

class NorDevice : public Device {
public:
    int read(int lba) override;
};

int devReadAny(Device* d, int lba);
int devReadNand(NandDevice& n, int lba);
