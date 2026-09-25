#include "LongDeclShapes.h"

// Uses every type above, so they are genuinely this unit's own and the unit has a function.
int longShapesChecksum(void) {
    LongRegisterBank bank;
    LongFrame frame;
    LongWord word;
    LongPacket_t packet;
    BraceInComment inComment;
    OpenBraceInComment openComment;
    BraceInString inString;
    Exactly60 e60;
    Exactly61 e61;
    (void)bank; (void)frame; (void)word; (void)packet; (void)inComment;
    (void)openComment; (void)inString; (void)e60; (void)e61;
    return (int)OP_LAST;
}
