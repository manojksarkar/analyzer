#pragma once

// Direction of a function that returns nothing (SWE3_WIKI SWE3-UI-05): writing what a
// pointer or reference parameter points at makes it In, like writing a global -- through
// `->`, `*`, `[]`, `*(p + i)`, `*p++`, a reference, or a local copy of the pointer. Moving
// the pointer itself (`p = p->next`) and writing a parameter passed by value do not count.
// App/Main.cpp calls every function here, so each one has an interface row.

struct PwNode { int length; PwNode* next; };

class PwPool {
public:
    typedef PwNode* P_PwNode;              // a pointer by typedef: no `*` in its spelling
};

class PwList {
public:
    void pwDeleteNode(PwPool::P_PwNode pNode);   // In: pNode->length, by a typedef pointer
};

void pwClearNode(PwNode* pNode);                 // In: pNode->length, pNode->next
void pwResetNode(PwNode& node);                  // In: a reference
void pwFillBuffer(int* buf, int n);              // In: *(buf + i)
void pwStepFill(int* buf, int n);                // In: *buf++
void pwClearViaCopy(PwPool::P_PwNode pNode);     // In: through a local copy of the pointer
void pwMarkViaRef(PwNode* pNode);                // In: through a local reference to *pNode
void pwWalk(PwPool::P_PwNode pNode);             // Out: moves the pointer, writes nothing
void pwByValue(PwNode node);                     // Out: writes its own copy
void pwClearNext(PwPool::P_PwNode pNode);        // Out: a pointer copied from pNode->next
void pwPassOn(PwNode* pNode);                    // Out: passed on, not followed
void pwLambda();                                 // Out: the lambda's parameter, not its own
