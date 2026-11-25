#pragma once

// Direction of a method that returns nothing (review SWE3-025, SWE3_WIKI SWE3-UI-05):
// writing a member variable of its OWN object makes it In, like writing a global --
// directly, through a method it calls on that object, or through a local pointer it points
// there. Another object's member does not count, unless the object is a parameter
// (ParamWrites.h); nor does a pointer a function returns.
// App/Main.cpp calls every public method here, so each one has an interface row.

struct MwEntry { int a; };
struct MwBlock { MwEntry xa[8]; };

class MwBase {
protected:
    int m_baseCount;
    MwEntry m_cx;
    static MwBlock s_block;
    void mwBaseReset();
};

class MwHelper {
public:
    void mwHelperReset();
private:
    int m_n;
};

class MwTable : public MwBase {
public:
    void mwDeleteEntry(int id);            // In: m_table[id], m_used
    void mwClearAll();                     // In: through mwDeleteEntry
    void mwResetAll();                     // In: through MwBase::mwBaseReset
    void mwBumpBase();                     // In: a base-class member, MwBase::m_cx
    void mwInsertX(int nodeid);            // In: s_block, a global, through a local pointer
    void mwMarkRow(int id);                // In: m_rows, through a local pointer
    void mwDump() const;                   // Out: reads only
    void mwCopyTo(MwTable& other) const;   // In: other.m_used, through its parameter
    void mwResetHelper();                  // Out: another object's method
    void mwMarkFound(int id);              // Out: a pointer a function returns
private:
    int m_table[16];
    int m_used;
    MwEntry m_rows[4];
    MwEntry* mwFind(int id);
};
