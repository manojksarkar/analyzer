// MissingHeaderSwitchUser.cpp — the caller in another unit that publishes
// missingHeaderSwitch (MissingHeaderSwitch.cpp), so it gets a section and a test specification.
extern int missingHeaderSwitch(int mode);

PUBLIC int missingHeaderSwitchProbe(int mode) {
    return missingHeaderSwitch(mode);
}
