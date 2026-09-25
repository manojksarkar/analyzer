#pragma once

// Test: the unit header table must show every declaration WHOLE, however long it is and
// whatever its comments and string literals hold. Access/LongDecls.h covers a long
// commented class, a `{` in a trailing comment and a long initializer; this file covers
// the other kinds past 60 lines, the other brace-in-noise cases, and the 60/61 boundary.
//
// Each type states what its cell must end with. Nothing is marked PUBLIC/PRIVATE and
// nothing is static: these types exist for the unit header table, not the interface table.

// 1. A CLASS of 70 lines: access labels, a nested enum (no row of its own) and an inline
//    body past line 60, which the cell lists as a declaration. Must end with
//    `int lastRegister;` and `};`.
class LongRegisterBank {
public:
    enum Mode { MODE_IDLE = 0, MODE_RUN = 1 };
    void reset(void);
    int r00;
    int r01;
    int r02;
    int r03;
    int r04;
    int r05;
    int r06;
    int r07;
    int r08;
    int r09;
    int r10;
    int r11;
    int r12;
    int r13;
    int r14;
    int r15;
    int r16;
    int r17;
    int r18;
    int r19;
    int r20;
    int r21;
    int r22;
    int r23;
    int r24;
    int r25;
    int r26;
    int r27;
    int r28;
    int r29;
    int r30;
    int r31;
    int r32;
    int r33;
    int r34;
    int r35;
    int r36;
    int r37;
    int r38;
    int r39;
    int r40;
    int r41;
    int r42;
    int r43;
    int r44;
    int r45;
    int r46;
    int r47;
    int r48;
    int r49;
    int r50;
    int r51;
    int r52;
    int r53;
    int r54;
    int r55;
    int r56;
    int r57;
    int r58;
    int r59;
    int r60;
    int r61;
    int width(void) const { return 32; }
private:
    int lastRegister;
};

// 2. A STRUCT of 66 lines. Must end with `unsigned char lastByte;` and `};`.
struct LongFrame {
    unsigned char b00;
    unsigned char b01;
    unsigned char b02;
    unsigned char b03;
    unsigned char b04;
    unsigned char b05;
    unsigned char b06;
    unsigned char b07;
    unsigned char b08;
    unsigned char b09;
    unsigned char b10;
    unsigned char b11;
    unsigned char b12;
    unsigned char b13;
    unsigned char b14;
    unsigned char b15;
    unsigned char b16;
    unsigned char b17;
    unsigned char b18;
    unsigned char b19;
    unsigned char b20;
    unsigned char b21;
    unsigned char b22;
    unsigned char b23;
    unsigned char b24;
    unsigned char b25;
    unsigned char b26;
    unsigned char b27;
    unsigned char b28;
    unsigned char b29;
    unsigned char b30;
    unsigned char b31;
    unsigned char b32;
    unsigned char b33;
    unsigned char b34;
    unsigned char b35;
    unsigned char b36;
    unsigned char b37;
    unsigned char b38;
    unsigned char b39;
    unsigned char b40;
    unsigned char b41;
    unsigned char b42;
    unsigned char b43;
    unsigned char b44;
    unsigned char b45;
    unsigned char b46;
    unsigned char b47;
    unsigned char b48;
    unsigned char b49;
    unsigned char b50;
    unsigned char b51;
    unsigned char b52;
    unsigned char b53;
    unsigned char b54;
    unsigned char b55;
    unsigned char b56;
    unsigned char b57;
    unsigned char b58;
    unsigned char b59;
    unsigned char b60;
    unsigned char b61;
    unsigned char b62;
    unsigned char lastByte;
};

// 3. A UNION of 63 lines. Must end with `long lastView;` and `};`.
union LongWord {
    int view00;
    int view01;
    int view02;
    int view03;
    int view04;
    int view05;
    int view06;
    int view07;
    int view08;
    int view09;
    int view10;
    int view11;
    int view12;
    int view13;
    int view14;
    int view15;
    int view16;
    int view17;
    int view18;
    int view19;
    int view20;
    int view21;
    int view22;
    int view23;
    int view24;
    int view25;
    int view26;
    int view27;
    int view28;
    int view29;
    int view30;
    int view31;
    int view32;
    int view33;
    int view34;
    int view35;
    int view36;
    int view37;
    int view38;
    int view39;
    int view40;
    int view41;
    int view42;
    int view43;
    int view44;
    int view45;
    int view46;
    int view47;
    int view48;
    int view49;
    int view50;
    int view51;
    int view52;
    int view53;
    int view54;
    int view55;
    int view56;
    int view57;
    int view58;
    int view59;
    long lastView;
};

// 4. An ENUM of 68 lines. The information column (NAME=value) comes from the model and was
//    always whole; the DECLARATION cell is what was cut. Must end with `OP_LAST = 99`, `};`.
enum LongOpcode {
    OP_00 = 0,
    OP_01 = 1,
    OP_02 = 2,
    OP_03 = 3,
    OP_04 = 4,
    OP_05 = 5,
    OP_06 = 6,
    OP_07 = 7,
    OP_08 = 8,
    OP_09 = 9,
    OP_10 = 10,
    OP_11 = 11,
    OP_12 = 12,
    OP_13 = 13,
    OP_14 = 14,
    OP_15 = 15,
    OP_16 = 16,
    OP_17 = 17,
    OP_18 = 18,
    OP_19 = 19,
    OP_20 = 20,
    OP_21 = 21,
    OP_22 = 22,
    OP_23 = 23,
    OP_24 = 24,
    OP_25 = 25,
    OP_26 = 26,
    OP_27 = 27,
    OP_28 = 28,
    OP_29 = 29,
    OP_30 = 30,
    OP_31 = 31,
    OP_32 = 32,
    OP_33 = 33,
    OP_34 = 34,
    OP_35 = 35,
    OP_36 = 36,
    OP_37 = 37,
    OP_38 = 38,
    OP_39 = 39,
    OP_40 = 40,
    OP_41 = 41,
    OP_42 = 42,
    OP_43 = 43,
    OP_44 = 44,
    OP_45 = 45,
    OP_46 = 46,
    OP_47 = 47,
    OP_48 = 48,
    OP_49 = 49,
    OP_50 = 50,
    OP_51 = 51,
    OP_52 = 52,
    OP_53 = 53,
    OP_54 = 54,
    OP_55 = 55,
    OP_56 = 56,
    OP_57 = 57,
    OP_58 = 58,
    OP_59 = 59,
    OP_60 = 60,
    OP_61 = 61,
    OP_62 = 62,
    OP_63 = 63,
    OP_64 = 64,
    OP_LAST = 99
};

// 5. A `typedef struct {...} Name;` of 64 lines -- the typedef path, not the record path.
//    Must end with `} LongPacket_t;`.
typedef struct {
    unsigned short word00;
    unsigned short word01;
    unsigned short word02;
    unsigned short word03;
    unsigned short word04;
    unsigned short word05;
    unsigned short word06;
    unsigned short word07;
    unsigned short word08;
    unsigned short word09;
    unsigned short word10;
    unsigned short word11;
    unsigned short word12;
    unsigned short word13;
    unsigned short word14;
    unsigned short word15;
    unsigned short word16;
    unsigned short word17;
    unsigned short word18;
    unsigned short word19;
    unsigned short word20;
    unsigned short word21;
    unsigned short word22;
    unsigned short word23;
    unsigned short word24;
    unsigned short word25;
    unsigned short word26;
    unsigned short word27;
    unsigned short word28;
    unsigned short word29;
    unsigned short word30;
    unsigned short word31;
    unsigned short word32;
    unsigned short word33;
    unsigned short word34;
    unsigned short word35;
    unsigned short word36;
    unsigned short word37;
    unsigned short word38;
    unsigned short word39;
    unsigned short word40;
    unsigned short word41;
    unsigned short word42;
    unsigned short word43;
    unsigned short word44;
    unsigned short word45;
    unsigned short word46;
    unsigned short word47;
    unsigned short word48;
    unsigned short word49;
    unsigned short word50;
    unsigned short word51;
    unsigned short word52;
    unsigned short word53;
    unsigned short word54;
    unsigned short word55;
    unsigned short word56;
    unsigned short word57;
    unsigned short word58;
    unsigned short word59;
    unsigned short word60;
    unsigned short lastWord;
} LongPacket_t;

// 6. A `}` inside a COMMENT on its own line. Counted as code, it closed the class there and
//    the cell stopped at the next `;`. Must end with `int afterBrace;` and `};`.
class BraceInComment {
public:
    int beforeBrace;
    // a closing brace } in a comment does not close the class
    int afterBrace;
};

// 7. A `{` inside a COMMENT on its own line. Counted as code, the class never closed and
//    the cell ran on into the declarations below it. Must be exactly these 5 lines.
class OpenBraceInComment {
public:
    // an opening brace { in a comment does not open anything
    int onlyMember;
};

// 8. Braces inside STRING and CHAR literals, in inline bodies. The cell lists each method as
//    its declaration; the step that does that counted the `{` in "{" as a body still open,
//    and dropped `afterOpen` and `closeMark` as if they were the rest of that body. All four
//    members must be listed, ending with `int tail;` and `};`.
class BraceInString {
public:
    const char* openMark(void) const { return "{"; }
    int afterOpen;
    char closeMark(void) const { return '}'; }
    int tail;
};

// 9. CONTROL: exactly 60 lines, closing on its 60th -- the longest declaration the old
//    reader already returned whole. Unchanged.
class Exactly60 {
public:
    int s00;
    int s01;
    int s02;
    int s03;
    int s04;
    int s05;
    int s06;
    int s07;
    int s08;
    int s09;
    int s10;
    int s11;
    int s12;
    int s13;
    int s14;
    int s15;
    int s16;
    int s17;
    int s18;
    int s19;
    int s20;
    int s21;
    int s22;
    int s23;
    int s24;
    int s25;
    int s26;
    int s27;
    int s28;
    int s29;
    int s30;
    int s31;
    int s32;
    int s33;
    int s34;
    int s35;
    int s36;
    int s37;
    int s38;
    int s39;
    int s40;
    int s41;
    int s42;
    int s43;
    int s44;
    int s45;
    int s46;
    int s47;
    int s48;
    int s49;
    int s50;
    int s51;
    int s52;
    int s53;
    int s54;
    int s55;
    int s56;
};

// 10. One line longer: 61 lines. The old reader lost only the closing `};`.
//     Must end with `int s57;` and `};`.
class Exactly61 {
public:
    int s00;
    int s01;
    int s02;
    int s03;
    int s04;
    int s05;
    int s06;
    int s07;
    int s08;
    int s09;
    int s10;
    int s11;
    int s12;
    int s13;
    int s14;
    int s15;
    int s16;
    int s17;
    int s18;
    int s19;
    int s20;
    int s21;
    int s22;
    int s23;
    int s24;
    int s25;
    int s26;
    int s27;
    int s28;
    int s29;
    int s30;
    int s31;
    int s32;
    int s33;
    int s34;
    int s35;
    int s36;
    int s37;
    int s38;
    int s39;
    int s40;
    int s41;
    int s42;
    int s43;
    int s44;
    int s45;
    int s46;
    int s47;
    int s48;
    int s49;
    int s50;
    int s51;
    int s52;
    int s53;
    int s54;
    int s55;
    int s56;
    int s57;
};
