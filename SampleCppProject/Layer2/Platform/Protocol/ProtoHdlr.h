#ifndef PROTOHDLR_H
#define PROTOHDLR_H

void proto_hdlr_register(int id, void (*fn)());
void proto_hdlr_dispatch(int id);

#endif // PROTOHDLR_H
