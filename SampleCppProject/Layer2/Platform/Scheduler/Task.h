#ifndef TASK_H
#define TASK_H

int task_create(void (*fn)(), int prio);
void task_destroy(int id);

#endif // TASK_H
