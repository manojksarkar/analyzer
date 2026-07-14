#ifndef GPIO_H
#define GPIO_H

void gpio_init();
void gpio_set(int pin, int val);
int gpio_get(int pin);

#endif // GPIO_H
