#include "AccessMatrix.h"

// Definitions live here while the labels live in the header, so every member below is
// the out-of-line case: the cursor the parser walks is in this file and carries no
// label, and clang still reports the access it was declared with.

int mtxUnmarkedCalled(int v) {
    return v + 1;
}

int mtxUnmarkedUncalled(int v) {
    return v + 2;
}

PUBLIC int mtxPublicUncalled(int v) {
    return v + 3;
}

int MtxNoLabel::hidden(int v) {
    return v + 4;
}

int MtxStruct::plain(int v) {
    return v + 5;
}

int MtxStruct::exposed(int v) {
    return v + 6;
}

int MtxStruct::exposedUncalled(int v) {
    return v + 7;
}

int MtxStruct::guarded(int v) {
    return v + 8;
}

int MtxStruct::sealed(int v) {
    return v + 9;
}

PRIVATE int MtxConflict::markedPrivateUnderPublic(int v) {
    return v + 10;
}

PUBLIC int MtxConflict::markedPublicUnderPrivate(int v) {
    return v + 11;
}
