#include "NestedTypes.h"

// A different UNIT that calls into NestedOwner, so its two public methods earn interface
// rows. Without an outside caller both would be buried by the caller rule and the fixture
// would say nothing about which rows the interface table publishes.
//
// Nothing here can name NestedOwner's private types or s_privateSecret -- that is the
// point: they are unreachable from this unit, yet they still belong in NestedTypes's own
// unit header table.

int nestedUserProbe(int v) {
    int a = NestedOwner::nestedApply(v);
    int b = NestedOwner::nestedPublicMode(NestedOwner::NM_SAFE);
    return a + b + NestedOwner::s_publicCount;
}
