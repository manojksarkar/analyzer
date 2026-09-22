#include "AccessCompanion.h"

// A different UNIT in the same component -- the caller that genuinely publishes. Without
// this file every cell in the fixture would be buried for want of a caller, and the
// fixture would prove nothing about WHERE the caller sits.

int companionUserProbe(int v) {
    CompanionOwner owner;
    return owner.companionFromOtherUnit(v) + companionHeaderInline(v) + companionEntry(v);
}
