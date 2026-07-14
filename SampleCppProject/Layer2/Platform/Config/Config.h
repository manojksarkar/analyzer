#ifndef CONFIG_H
#define CONFIG_H

void cfg_init();
int cfg_get_int(const char *key);
void cfg_set_int(const char *key, int val);

#endif // CONFIG_H
