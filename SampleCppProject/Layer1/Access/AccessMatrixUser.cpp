#include "AccessMatrix.h"

// The cross-file callers. They exist so the restricted members are genuinely CALLED from
// another file: without them "protected/private is still PIF_" would prove nothing, since
// an uncalled member is buried anyway and the test would pass for the wrong reason.

// A derived class is the only legal way to reach a protected member from outside.
class MtxDerived : public MtxStruct {
public:
    PUBLIC int useGuarded(int v) { return guarded(v); }
};

// A friend reaches a private one. Declared inside MtxStruct, defined here.
PUBLIC int mtxCallSealed(MtxStruct &s) {
    return s.sealed(1);
}

// Same for the member whose PUBLIC macro overrides its `private:` label.
PUBLIC int mtxCallMarkedPublic(MtxConflict &c) {
    return c.markedPublicUnderPrivate(2);
}

PUBLIC int mtxUseDerived(int v) {
    MtxDerived d;
    return d.useGuarded(v);
}
