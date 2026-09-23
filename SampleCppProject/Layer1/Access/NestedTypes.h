#pragma once

// Every access position x every KIND of declaration, in one class, to pin down what an
// access specifier does to the unit header table.
//
// The rule (SWE3_WIKI N.1.4): access hides VARIABLES, never types. A type carries no
// visibility in the model at all -- the parser records an ENUM_DECL/TYPEDEF_DECL/
// STRUCT_DECL without ever reading `cursor.access_specifier` -- so a nested type under
// `private:` is listed exactly as one written at file scope.
//
// Deliberately NOT annotated PRIVATE/PUBLIC/PROTECTED: the C++ label must be the only
// marking here, or the macro scan answers first and the labels are never consulted.
//
// The interface table is the other half of the contract: only `s_publicCount` and
// `nestedApply` may appear there.
// A UNION and a C++11 `using` alias at file scope. Neither reached the data dictionary
// before 2026-09-23: UNION_DECL and TYPE_ALIAS_DECL were unhandled cursor kinds, so they
// appeared in no table at any access level, while a `typedef union {...} U;` came through
// its typedef. Both must now be listed like a struct and a typedef.
union NestedWord {
    unsigned int whole;
    unsigned char bytes[4];
};

using NestedAlias_t = unsigned short;

class NestedOwner {
public:
    enum PublicMode { NM_FAST = 0, NM_SAFE = 1 };
    typedef int PublicKey_t;
    struct PublicSlot { int id; int used; };

    static int s_publicCount;

    static int nestedApply(int v);
    static int nestedPublicMode(PublicMode m);

protected:
    // Listed in the unit header table (a type), unlike s_protectedMark below (a variable
    // -- protected collapses to private and is left out of the interface table).
    enum ProtectedFlag { NF_NONE = 0, NF_SET = 1 };

    static int s_protectedMark;

private:
    // A nested union and a nested alias: like the nested enum/typedef/struct above, the
    // class's own declaration shows them, so neither gets a row of its own.
    union PrivateWord { unsigned int whole; unsigned char bytes[4]; };
    using PrivateAlias_t = unsigned char;

    // All three ARE listed in the unit header table. The interface table never contains a
    // type at any access level, so nothing here is published as an interface.
    enum PrivateState { NS_IDLE = 0, NS_BUSY = 1 };
    typedef unsigned char PrivateByte_t;
    struct PrivateSlot { int id; };

    // A variable, so `private:` does hide it -- from the interface table only. It still
    // appears in the unit header table, because nestedApply's flowchart names it.
    static int s_privateSecret;
};
