#pragma once

// A static member does not have to be a scalar. This is the shape a cache keeps its
// bookkeeping in, and the one the field-write path below is about.
struct StatCounts {
    int inserts;
    int hits;
};

// Test: `static` DATA MEMBERS -- shared, program-lifetime storage under a class's name.
// Clang parents them on the class, not the translation unit, so they used to be dropped
// from globalVariables.json, from the read/write sets behind the In/Out direction, and
// from every SWE.4 precondition.
//
// Deliberately NOT annotated PRIVATE/PUBLIC/PROTECTED -- visibility here must be read from
// the C++ access specifier. An annotated declaration still wins where one exists.
class StatCounters {
public:
    // Declared here, DEFINED in ClassStatics.cpp: two cursors, one variable, one entry.
    static int s_publicCount;

    // AGGREGATE static member. Every write below reaches it through a FIELD
    // (`StatCounters::s_counts.inserts++`), never by naming the member alone, so the
    // walker only records the write if it carries is_write down the MEMBER_REF_EXPR to
    // its base. Miss that and the access lands in the READ set instead -- the one
    // outcome that is worse than losing it, because a void function whose whole job is
    // to bump a counter then reads out as Out.
    static StatCounts s_counts;

    // In-class initialised, so there is NO out-of-line definition anywhere. Nothing to
    // collapse onto -- this declaration is the only cursor and must still be recorded.
    static const int s_limit = 7;

    // NOT static: a FIELD_DECL, a different cursor kind. Must never become a global.
    int m_instance;

protected:
    static int s_protectedMark;

private:
    // Recorded (direction and the test specs need it) but unreachable from another unit,
    // so it must NOT be published as an interface row.
    static int s_privateSecret;

    // statBumpPrivate() is a free function, so C++ access control has to be told it may
    // touch this member. `friend` grants exactly that and leaves the member PRIVATE, which
    // is the point of the case: visibility still excludes it from the interface table.
    // Without this the translation unit does not compile -- clang error-recovers and the
    // walker still sees the write, so every test passed while the fixture was invalid.
    friend void statBumpPrivate(void);
};

// ---------------------------------------------------------------------------------------
// Test: a PUBLIC METHOD bumping a PROTECTED static OF ITS OWN CLASS, through a field, with
// the member's type coming from another namespace. Every other static-member case here is
// written by a FREE function needing a `friend`; a member needs none -- it may reach its
// own class's protected statics. Nothing covered this shape, and it is the one real
// firmware uses.
//
// What it pins down: `protected` costs the member its interface row and NOTHING else. The
// member stays in the write set, so a void method with no Get/Set in its name still comes
// out In. Lose the write -- through the field hop, or through the namespace-qualified type
// -- and it reads out as Out, the exact inverse.
// ---------------------------------------------------------------------------------------
namespace XY {
struct AB {
    int member;
    int spare;
};
}

class NsCounters {
public:
    // void, no Get/Set, no return value -> rule 3, and the write set alone answers -> In.
    // CLASS-QUALIFIED reference: `NsCounters::var.member++`.
    void bumpNs(void);

    // The same write written UNQUALIFIED -- `var.member++` -- which is how a member
    // normally reaches its own class's static. A different cursor shape from the line
    // above, so it is asserted separately: if only the qualified form resolves, a void
    // bumper silently reads out as Out.
    void bumpNsPlain(void);

    // The mirror: same member, same field, reads and writes nothing -> Out. A walker that
    // logged every member access as a write would pass bumpNs and still be wrong here.
    void peekNs(void);

protected:
    static XY::AB var;
};

// The third form: the CLASS ITSELF inside a namespace, so the member is reached as
// `NS::Wrapped::var`. Nothing else here nests a class in a namespace.
namespace NS {
class Wrapped {
public:
    void bumpWrapped(void);

protected:
    static XY::AB var;
};
}

// All void-returning and free of Get/Set, so direction falls through to the global-access
// rule -- the rule a static member was invisible to. Annotated PUBLIC because nothing in the
// sample calls them across units, and an un-annotated function with no external caller is
// inferred private and dropped from the interface table.
PUBLIC void statBumpPublic(void);
PUBLIC void statReadPublic(void);
PUBLIC void statBumpPrivate(void);
PUBLIC void statBumpIndirect(void);
PUBLIC void statBumpRegistry(void);

// The FIELD-write group: void, no Get/Set in the name, so each one falls through to the
// global-access rule and its direction is decided purely by what the walker recorded.
// `Insert` also guards the name tokenizer -- it CONTAINS the letters of "set" and must
// not be read as a setter (the _WORD_RE whole-word rule, model_deriver.py).
PUBLIC void statInsertCache(void);      // postfix bump of a field  -> In
PUBLIC void statPrimeCache(void);       // plain assign to a field  -> In
PUBLIC void statAddCacheHits(void);     // compound assign: write AND read -> In
PUBLIC void statReadCacheHits(void);    // reads a field, writes none -> Out

// Returns a value, so direction is decided before globals are consulted.
PUBLIC int statReadLimit(void);

// Defined in ClassStaticsUser.cpp -- a SECOND translation unit touching the same member.
PUBLIC void statBumpFromOtherUnit(void);
