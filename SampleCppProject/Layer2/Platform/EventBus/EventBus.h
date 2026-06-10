#ifndef EVENTBUS_H
#define EVENTBUS_H

void evb_init();
void evb_publish(int id);
void evb_subscribe(int id, void (*cb)());

#endif // EVENTBUS_H
